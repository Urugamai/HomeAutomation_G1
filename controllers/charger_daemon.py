import sys
import time
import json
from datetime import datetime
from pathlib import Path
import configparser

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing. Run 'pip install paho-mqtt'.")
    sys.exit(1)

# Safe fallback structure if running on an isolated test machine without network modules
try:
    from pymodbus.client import ModbusTcpClient

    MODBUS_AVAILABLE = True
except ImportError:
    MODBUS_AVAILABLE = False


class OcularChargerDaemon:
    """
    Background supervisor for the Ocular EV Charger.
    Manages ModbusTCP register queries and optimizes vehicle charging power
    against off-peak utility periods and solar battery status levels.
    """

    def __init__(self):
        print("[INIT] Launching Ocular EV Charger Controller Daemon...")

        # Load structural networking configurations
        self.broker_ip = self._load_config_value("MQTT", "broker", "localhost")
        self.charger_ip = self._load_config_value("CHARGER", "ip_address", "192.168.1.50")
        self.charger_port = int(self._load_config_value("CHARGER", "port", "502"))

        # Local Management Variables (Synced continuously via Sigen MQTT telemetry data)
        self.battery_soc = 50
        self.grid_flow_watts = 0
        self.solar_generation_kwh = 0

        # Internal Tracking Flags
        self.current_charge_rate_amps = 0
        self.is_charging_allowed = False

        # Connect to the physical charger interface
        if MODBUS_AVAILABLE:
            self.modbus_client = ModbusTcpClient(self.charger_ip, port=self.charger_port)
            print(f"[MODBUS] Driver ready for hardware endpoint -> {self.charger_ip}:{self.charger_port}")
        else:
            self.modbus_client = None
            print("[MODBUS WARN] 'pymodbus' not available. Running in local virtual simulation mode.")

    def _load_config_value(self, section, key, fallback) -> str:
        config_path = Path(__file__).resolve().parent / "config.ini"
        if config_path.exists():
            try:
                config = configparser.ConfigParser()
                config.read(str(config_path))
                return config.get(section, key, fallback=fallback)
            except Exception:
                pass
        return fallback

    def start(self):
        # Configure and start the MQTT background network worker thread
        self.mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message

        try:
            self.mqtt_client.connect(self.broker_ip, 1883, keepalive=60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"[NETWORK ERROR] Charger Daemon broker handshake failed: {e}")

        print("[RUNNING] EV optimization framework active. Evaluating charge rules...")
        try:
            while True:
                # Core operational loop: updates data maps and monitors hardware every 10 seconds
                self._evaluate_and_apply_charging_logic()
                self._publish_charger_status_to_broker()
                time.sleep(10.0)
        except KeyboardInterrupt:
            print("[SHUTDOWN] Halting EV Charger background processes. Zeroing pilot currents.")
            self._write_modbus_charge_rate(0)  # Immediately stop charging for safety
            self.mqtt_client.loop_stop()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        print(f"[MQTT] Charger Daemon bound to broker ({self.broker_ip}). Listening for power signals.")
        # Listen for real-time asset flows coming from your Sigen storages or manual overwrites
        self.mqtt_client.subscribe("home/power/sigen")
        self.mqtt_client.subscribe("home/ocular/command")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))

            if msg.topic == "home/power/sigen":
                # Ingest active metrics from the home battery system
                self.battery_soc = int(payload.get("battery_soc", self.battery_soc))
                self.grid_flow_watts = int(payload.get("grid_flow", self.grid_flow_watts))
                self.solar_generation_kwh = float(payload.get("solar_kwh_today", self.solar_generation_kwh))

            elif msg.topic == "home/ocular/command":
                # Manual priority override mechanism
                forced_state = payload.get("state")
                if forced_state == "OFF":
                    self.is_charging_allowed = False
                    self._write_modbus_charge_rate(0)
                    print("[OVERRIDE] Received manual stop command. Terminating EV session.")

        except Exception as e:
            print(f"[PARSE EXCEPTION] Charger Daemon failed to interpret incoming payload: {e}")

    def _evaluate_and_apply_charging_logic(self):
        """Processes energy constraints to optimize the charging cycle."""
        now = datetime.now()
        is_weekend = now.weekday() >= 5

        # Enforce target off-peak utility pricing window rules (23:00 to 07:00 weekdays, all day weekends)
        is_off_peak = (now.hour >= 23 or now.hour < 7) or is_weekend

        target_amps = 0  # 0 Amps represents an electronic standby/stop state

        if is_off_peak:
            # Rule A: Off-peak window is wide open. Charge safely at a standard overnight rate.
            target_amps = 16  # Standard single-phase 3.6kW charging speed
            self.is_charging_allowed = True

        else:
            # Rule B: Peak rate window is active. Rely exclusively on excess solar generation rules.
            # Grid export is represented as a negative number in your Sigen schema (e.g., -1500W means 1.5kW exporting).
            if self.grid_flow_watts < -2000:
                # We have more than 2kW of excess solar leaking back into the grid. Absorb it!
                excess_watts = abs(self.grid_flow_watts)
                # Quick translation index: Amps = Watts / 230V
                calculated_amps = int(excess_watts / 230)
                target_amps = min(max(calculated_amps, 6), 32)  # Clamp between safe EVSE limits (6A min, 32A max)
                self.is_charging_allowed = True
                print(f"[OPTIMIZER] Peak hours solar tracking active. Diverting surplus: {target_amps}A")

            # Rule C: Protect home storage battery. Stop vehicle charging if house battery reserves drop below 80%.
            elif self.battery_soc >= 100:
                target_amps = 6  # Maintain a minimal trickle charge since home energy banks are entirely full
                self.is_charging_allowed = True
            elif self.battery_soc <= 80:
                target_amps = 0  # Isolate car charging to prevent draining the home storage system during peak hours
                self.is_charging_allowed = False

        # Apply changes if the calculated rate differs from the current configuration
        if target_amps != self.current_charge_rate_amps:
            self._write_modbus_charge_rate(target_amps)

    def _write_modbus_charge_rate(self, amps: int):
        """Communicates physical register adjustments over Modbus TCP to the charger."""
        self.current_charge_rate_amps = amps
        if not self.modbus_client:
            return

        try:
            if not self.modbus_client.connected:
                self.modbus_client.connect()

            # Example standard register maps for Ocular/EVSE wallboxes:
            # Register 200: Sets current allowance limitations (Writeable Holding Register)
            # Register 101: Session Enable configuration toggle switches
            if amps > 0:
                self.modbus_client.write_register(address=200, value=amps, slave=1)
                self.modbus_client.write_register(address=101, value=1, slave=1)  # Enable Charge
            else:
                self.modbus_client.write_register(address=200, value=0, slave=1)
                self.modbus_client.write_register(address=101, value=0, slave=1)  # Disable Charge

        except Exception as e:
            print(f"[MODBUS HARDWARE EXCEPTION] Failed writing to Ocular registers: {e}")

    def _publish_charger_status_to_broker(self):
        """Feeds monitoring metrics back to your touchscreen dashboards."""
        status_packet = {
            "charger_state": "ON" if self.current_charge_rate_amps > 0 else "OFF",
            "pilot_current_amps": self.current_charge_rate_amps,
            "power_draw_kw": round((self.current_charge_rate_amps * 230) / 1000, 2),
            "charging_allowed": self.is_charging_allowed
        }
        self.mqtt_client.publish("home/ocular/status", json.dumps(status_packet), retain=True)


if __name__ == "__main__":
    daemon = OcularChargerDaemon()
    daemon.start()
