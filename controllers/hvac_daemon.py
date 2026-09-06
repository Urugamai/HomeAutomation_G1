import sys
import time
import json
from pathlib import Path
import configparser

# Safe fallback logic loops for physical hardware interaction bindings
try:
    import smbus2

    IS_RASPI = True
except ImportError:
    smbus2 = None
    IS_RASPI = False

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing. Run 'pip install paho-mqtt'.")
    sys.exit(1)

from libraries.paho_compat import create_client


class HvacHardwareDaemon:
    """
    Independent background loop driving real-time Raspberry Pi I2C relays,
    BME climate polling, and safe HVAC sequencing limits.
    """
    I2C_RELAY_ADDR = 0x20  # Expander line module address (e.g. PCF8574)
    I2C_BME_ADDR = 0x76  # Dynamic climate sensor address trace target

    def __init__(self):
        print(f"[INIT] Launching HVAC Daemon Subsystem. Platform Native Pi = {IS_RASPI}")

        # Load configuration values
        self.broker_ip = self._load_broker_config()

        # Operational Boundaries (Synchronised via UI / Retained Broker Messages)
        self.t_min = 20.0
        self.t_max = 24.0

        # Run State Machine Flags
        self.current_state = "OFF"  # Expected options: OFF, HEATING, COOLING
        self.last_state_change = time.time()
        self.in_rest_period = False
        self.rest_start_time = 0.0
        self.blind_pre_close_triggered = False

        # Initialize physical bus frameworks
        if IS_RASPI and smbus2:
            try:
                self.bus = smbus2.SMBus(1)
                self._write_relays("OFF")  # Enforce clean isolation on start
            except Exception as e:
                print(f"[I2C ERROR] Could not bind physical I2C interface lines: {e}")
                self.bus = None
        else:
            self.bus = None

    def _load_broker_config(self) -> str:
        config_path = Path(__file__).resolve().parent / "config.ini"
        if config_path.exists():
            try:
                config = configparser.ConfigParser()
                config.read(str(config_path))
                return config.get("MQTT", "broker", fallback="localhost")
            except Exception:
                pass
        return "localhost"

    def start(self):
        """Initializes network broker pipelines and core processing timers."""
        self.client = create_client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        try:
            self.client.connect(self.broker_ip, 1883, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            print(f"[NETWORK ERROR] Broker handshake failed: {e}")

        # Primary Core Execution Loop
        print("[RUNNING] Safety management matrix armed. Processing cycles active.")
        try:
            while True:
                self._process_control_tick()
                time.sleep(5.0)  # Evaluate state transformations every 5 seconds
        except KeyboardInterrupt:
            print("[SHUTDOWN] Terminating background daemons. Isolating contactors.")
            self._write_relays("OFF")
            self.client.loop_stop()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        print(f"[MQTT] Connected successfully to broker ({self.broker_ip}). Listening for adjustments...")
        # Subscribe to dynamic UI targets
        self.client.subscribe("home/hvac/settings")

    def _on_message(self, client, userdata, msg):
        try:
            if msg.topic == "home/hvac/settings":
                payload = json.loads(msg.payload.decode('utf-8'))
                self.t_min = float(payload.get("target_min", self.t_min))
                self.t_max = float(payload.get("target_max", self.t_max))
                print(f"[SETTINGS UPDATED] Min Threshold: {self.t_min}°C | Max Threshold: {self.t_max}°C")
        except Exception as e:
            print(f"[PARSE EXCEPTION] Bad configuration update payload structure: {e}")

    def _read_inside_temperature(self) -> float:
        """Polls physical sensory inputs on the I2C line, falling back to dummy metrics if off-board."""
        if IS_RASPI and self.bus:
            try:
                # Basic register read template mapping BME sensor data
                # (Replace with an imported bme280 package block for production calibration)
                data = self.bus.read_byte_data(self.I2C_BME_ADDR, 0xFA)
                # Synthetic alignment mimicking typical sensor returns for demo fallback stability
                return round(21.5 + (data % 5) * 0.2, 1)
            except Exception:
                pass
        # Accurate baseline metric simulation for Windows environment testing
        return 22.0

    def _write_relays(self, mode: str):
        """
        Enforces a strict mutually exclusive mechanical/software configuration:
        Relay 1 (Heating) and Relay 2 (Cooling) can NEVER be driven hot simultaneously.
        """
        if not IS_RASPI or not self.bus:
            return

        # Bit definitions: Bit 0 = Heat Relay, Bit 1 = Cool Relay, Bit 2 = Master Fan Enable
        if mode == "HEATING":
            byte_payload = 0x05  # 0b00000101 -> Heat On, Fan On, Cool Off
        elif mode == "COOLING":
            byte_payload = 0x06  # 0b00000110 -> Cool On, Fan On, Heat Off
        else:
            byte_payload = 0x00  # 0b00000000 -> All Isolators Open (OFF)

        try:
            self.bus.write_byte_data(self.I2C_RELAY_ADDR, 0, byte_payload)
        except Exception as e:
            print(f"[HARDWARE EXCEPTION] Failed writing command to physical I2C expander: {e}")

    def _process_control_tick(self):
        """Evaluates HVAC safety rules, time tracking metrics, and structural thresholds."""
        current_temp = self._read_inside_temperature()
        now = time.time()

        # Rule 1: Manage Rest Cycle Enforcements
        if self.in_rest_period:
            elapsed_rest = now - self.rest_start_time
            if elapsed_rest >= 300:  # 5 Minute rest completed (300 seconds)
                print("[SAFETY] 5-minute mandatory runtime rest interval cleared. Resuming control access.")
                self.in_rest_period = False
            else:
                if self.current_state != "OFF":
                    self.current_state = "OFF"
                    self._write_relays("OFF")
                self._broadcast_status_telemetry(current_temp)
                return

        # Rule 2: Enforce Maximum Active Continuous Run Window Limits
        if self.current_state in ["HEATING", "COOLING"]:
            active_duration = now - self.last_state_change
            if active_duration >= 600:  # 10 Minute max execution boundary (600 seconds)
                print(f"[SAFETY] Max 10-minute active run limit hit during {self.current_state}. Entering rest period.")
                self.current_state = "OFF"
                self._write_relays("OFF")
                self.in_rest_period = True
                self.rest_start_time = now
                self.blind_pre_close_triggered = False
                self._broadcast_status_telemetry(current_temp)
                return

        # Rule 3: Evaluate Automation State Limits & Trigger Preparatory Commands
        target_state = "OFF"

        # Advance Warning Trigger: 1°C Buffer checks before active heating/cooling engagement zones
        if current_temp <= (self.t_min + 1.0) and current_temp < self.t_max:
            if not self.blind_pre_close_triggered and self.current_state == "OFF":
                print("[AUTOMATION] Temperature approaching low limits. Issuing anticipatory blind close command.")
                self.client.publish("home/blinds/command", json.dumps({"action": "CLOSE", "reason": "HVAC_PREHEAT"}))
                self.blind_pre_close_triggered = True
        elif current_temp >= (self.t_max - 1.0) and current_temp > self.t_min:
            if not self.blind_pre_close_triggered and self.current_state == "OFF":
                print("[AUTOMATION] Temperature approaching high limits. Issuing anticipatory blind close command.")
                self.client.publish("home/blinds/command", json.dumps({"action": "CLOSE", "reason": "HVAC_PRECOOL"}))
                self.blind_pre_close_triggered = True

        # Core Switching Logic
        if current_temp < self.t_min:
            target_state = "HEATING"
        elif current_temp > self.t_max:
            target_state = "COOLING"

        # Apply state changes safely
        if target_state != self.current_state:
            print(f"[STATE TRANSITION] Shifting operation profile: {self.current_state} -> {target_state}")
            self.current_state = target_state
            self.last_state_change = now
            self._write_relays(target_state)
            if target_state == "OFF":
                self.blind_pre_close_triggered = False  # Reset flags on idle

        # Broadcast telemetry feedback package to your network screens
        self._broadcast_status_telemetry(current_temp)

    def _broadcast_status_telemetry(self, current_temp: float):
        """Pushes health data updates back out over the broker line to feed adaptive layouts."""
        telemetry_packet = {
            "temperature": current_temp,
            "hvac_state": self.current_state,
            "hvac_in_rest": self.in_rest_period
        }
        # Publish to separate sensor node trace targets to ensure clean modular consumption loops
        self.client.publish("home/environment/inside", json.dumps(telemetry_packet))


if __name__ == "__main__":
    daemon = HvacHardwareDaemon()
    daemon.start()
