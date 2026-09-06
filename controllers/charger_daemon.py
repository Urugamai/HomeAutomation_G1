import sys
import time
import json
from datetime import datetime
from pathlib import Path
import configparser

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing from active environment.")
    sys.exit(1)

from libraries.paho_compat import create_client

try:
    from pymodbus.client import ModbusTcpClient

    MODBUS_AVAILABLE = True
except ImportError:
    MODBUS_AVAILABLE = False


class OcularChargerDaemon:
    """
    Background supervisor for the Ocular EV Charger.
    Monitors Sigen power telemetry feeds and enforces off-peak/surplus charging rates.
    """

    def __init__(self):
        print("[INIT] Launching Ocular EV Charger Controller Daemon...")
        self.broker_ip = self._get_config_str("MQTT", "broker", "localhost")
        self.charger_ip = self._get_config_str("CHARGER", "ip_address", "192.168.1.50")
        self.charger_port = int(self._get_config_str("CHARGER", "port", "502"))

        self.battery_soc = 50
        self.grid_flow_watts = 0
        self.current_charge_rate_amps = 0

        if MODBUS_AVAILABLE:
            self.modbus_client = ModbusTcpClient(self.charger_ip, port=self.charger_port)
        else:
            self.modbus_client = None

    def _get_config_str(self, section, key, fallback) -> str:
        config_path = Path(__file__).resolve().parent.parent / "config.ini"
        if config_path.exists():
            try:
                config = configparser.ConfigParser()
                config.read(str(config_path))
                return config.get(section, key, fallback=fallback)
            except Exception:
                pass
        return fallback

    def start(self):
        self.mqtt_client = create_client()
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message

        try:
            self.mqtt_client.connect(self.broker_ip, 1883, keepalive=60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"[NETWORK ERROR] Charger Daemon broker link failed: {e}")

        try:
            while True:
                self._evaluate_charging_logic()
                time.sleep(10.0)
        except KeyboardInterrupt:
            self._write_modbus_rate(0)
            self.mqtt_client.loop_stop()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        client.subscribe("home/power/sigen")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            if msg.topic == "home/power/sigen":
                self.battery_soc = int(payload.get("battery_soc", self.battery_soc))
                self.grid_flow_watts = int(payload.get("grid_flow", self.grid_flow_watts))
        except Exception:
            pass

    def _evaluate_charging_logic(self):
        now = datetime.now()
        is_weekend = now.weekday() >= 5
        is_off_peak = (now.hour >= 23 or now.hour < 7) or is_weekend

        target_amps = 0

        if is_off_peak:
            target_amps = 16  # Active baseline single-phase profile
        else:
            if self.grid_flow_watts < -2000:  # Surplus solar available
                calculated_amps = int(abs(self.grid_flow_watts) / 230)
                target_amps = min(max(calculated_amps, 6), 32)
            elif self.battery_soc <= 80:
                target_amps = 0  # Conserve house reserves

        if target_amps != self.current_charge_rate_amps:
            self._write_modbus_rate(target_amps)

    def _write_modbus_rate(self, amps: int):
        self.current_charge_rate_amps = amps
        if not self.modbus_client:
            return
        try:
            if not self.modbus_client.connected:
                self.modbus_client.connect()
            self.modbus_client.write_register(address=200, value=amps, slave=1)
        except Exception as e:
            print(f"[MODBUS ERROR] Charger connection timed out: {e}")


if __name__ == "__main__":
    daemon = OcularChargerDaemon()
    daemon.start()
