import sys
import time
import json
import math
import threading
from pathlib import Path
import configparser

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

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
        self._settings_lock = threading.RLock()
        self.t_min = 20.0
        self.t_max = 24.0
        self.fan_preheat_seconds = 60.0
        self.fan_postrun_seconds = 120.0
        self.min_run_seconds = 300.0
        self.max_run_seconds = 600.0
        self.rest_seconds = 300.0

        # Run State Machine Flags
        self.current_state = "OFF"  # Expected options: OFF, HEATING, COOLING
        self.sequence_state = "OFF"
        self.pending_state = None
        self.sequence_started_at = time.time()
        self.active_run_started_at = None
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
        config_path = Path(__file__).resolve().parent.parent / "config.ini"
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
                settings = {
                    "t_min": float(payload.get("target_min", self.t_min)),
                    "t_max": float(payload.get("target_max", self.t_max)),
                    "fan_preheat_seconds": float(
                        payload.get("fan_preheat_seconds", self.fan_preheat_seconds)
                    ),
                    "fan_postrun_seconds": float(
                        payload.get("fan_postrun_seconds", self.fan_postrun_seconds)
                    ),
                    "min_run_seconds": float(
                        payload.get("min_run_seconds", self.min_run_seconds)
                    ),
                    "max_run_seconds": float(
                        payload.get("max_run_seconds", self.max_run_seconds)
                    ),
                    "rest_seconds": float(
                        payload.get("rest_seconds", self.rest_seconds)
                    ),
                }
                with self._settings_lock:
                    if not self._settings_are_valid(settings):
                        print("[SETTINGS REJECTED] HVAC timing or target thresholds are invalid.")
                        return
                    for name, value in settings.items():
                        setattr(self, name, value)
                print(
                    f"[SETTINGS UPDATED] Min: {self.t_min}°C | Max: {self.t_max}°C | "
                    f"Preheat: {self.fan_preheat_seconds}s | Postrun: {self.fan_postrun_seconds}s"
                )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as e:
            print(f"[PARSE EXCEPTION] Bad configuration update payload structure: {e}")

    @staticmethod
    def _settings_are_valid(settings: dict) -> bool:
        values = tuple(settings.values())
        return (
            all(math.isfinite(value) for value in values)
            and settings["t_min"] < settings["t_max"]
            and settings["min_run_seconds"] > 0
            and settings["max_run_seconds"] >= settings["min_run_seconds"]
            and settings["fan_preheat_seconds"] >= 0
            and settings["fan_postrun_seconds"] >= 0
            and settings["rest_seconds"] >= 0
        )

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
        elif mode == "FAN":
            byte_payload = 0x04  # 0b00000100 -> Fan On, Heat and Cool Off
        else:
            byte_payload = 0x00  # 0b00000000 -> All Isolators Open (OFF)

        try:
            self.bus.write_byte_data(self.I2C_RELAY_ADDR, 0, byte_payload)
        except Exception as e:
            print(f"[HARDWARE EXCEPTION] Failed writing command to physical I2C expander: {e}")

    def _process_control_tick(self):
        with self._settings_lock:
            self._process_control_tick_locked()

    def _process_control_tick_locked(self):
        """Evaluates HVAC safety rules, time tracking metrics, and structural thresholds."""
        current_temp = self._read_inside_temperature()
        now = time.time()

        if self.sequence_state == "POSTRUN":
            if now - self.sequence_started_at >= self.fan_postrun_seconds:
                self.sequence_state = "OFF"
                self.pending_state = None
                self._write_relays("OFF")
                self.blind_pre_close_triggered = False
            self._broadcast_status_telemetry(current_temp)
            return

        if self.in_rest_period:
            if now - self.rest_start_time >= self.rest_seconds:
                print("[SAFETY] Mandatory runtime rest interval cleared. Resuming control access.")
                self.in_rest_period = False
            else:
                self._broadcast_status_telemetry(current_temp)
                return

        target_state = self._requested_state(current_temp)

        if self.sequence_state == "PREHEAT":
            if target_state != self.pending_state:
                if target_state == "OFF":
                    self.sequence_state = "OFF"
                    self.pending_state = None
                    self._write_relays("OFF")
                else:
                    self.pending_state = target_state
                    self.sequence_started_at = now
            elif now - self.sequence_started_at >= self.fan_preheat_seconds:
                self._start_active_run(self.pending_state, now)
            self._broadcast_status_telemetry(current_temp)
            return

        if self.current_state in ("HEATING", "COOLING"):
            active_duration = now - self.active_run_started_at
            if active_duration >= self.max_run_seconds:
                print(f"[SAFETY] Maximum active run reached during {self.current_state}. Entering rest.")
                self._end_active_run(now, start_rest=True)
            elif target_state != self.current_state and active_duration >= self.min_run_seconds:
                print(f"[STATE TRANSITION] Ending {self.current_state} after minimum run period.")
                self._end_active_run(now)
            self._broadcast_status_telemetry(current_temp)
            return

        if target_state != "OFF":
            self._start_preheat(target_state, now)
        else:
            self._maybe_close_blinds(current_temp)
        self._broadcast_status_telemetry(current_temp)

    def _requested_state(self, current_temp: float) -> str:
        if current_temp < self.t_min:
            return "HEATING"
        if current_temp > self.t_max:
            return "COOLING"
        return "OFF"

    def _start_preheat(self, target_state: str, now: float):
        self.pending_state = target_state
        self.sequence_state = "PREHEAT"
        self.sequence_started_at = now
        self._write_relays("FAN")
        self._maybe_close_blinds_for_state(target_state)
        if self.fan_preheat_seconds == 0:
            self._start_active_run(target_state, now)

    def _start_active_run(self, target_state: str, now: float):
        self.current_state = target_state
        self.pending_state = None
        self.sequence_state = target_state
        self.active_run_started_at = now
        self._write_relays(target_state)
        print(f"[STATE TRANSITION] Active {target_state} run started.")

    def _end_active_run(self, now: float, start_rest: bool = False):
        self.current_state = "OFF"
        self.active_run_started_at = None
        self.sequence_state = "POSTRUN"
        self.sequence_started_at = now
        self._write_relays("FAN" if self.fan_postrun_seconds > 0 else "OFF")
        if self.fan_postrun_seconds == 0:
            self.sequence_state = "OFF"
        if start_rest:
            self.in_rest_period = True
            self.rest_start_time = now

    def _maybe_close_blinds(self, current_temp: float):
        if current_temp <= self.t_min + 1.0:
            self._maybe_close_blinds_for_state("HEATING")
        elif current_temp >= self.t_max - 1.0:
            self._maybe_close_blinds_for_state("COOLING")

    def _maybe_close_blinds_for_state(self, target_state: str):
        if not self.blind_pre_close_triggered:
            reason = "HVAC_PREHEAT" if target_state == "HEATING" else "HVAC_PRECOOL"
            print("[AUTOMATION] Issuing anticipatory blind close command.")
            self.client.publish("home/blinds/command", json.dumps({"action": "CLOSE", "reason": reason}))
            self.blind_pre_close_triggered = True

    def _broadcast_status_telemetry(self, current_temp: float):
        """Pushes health data updates back out over the broker line to feed adaptive layouts."""
        telemetry_packet = {
            "temperature": current_temp,
            "hvac_state": self.current_state,
            "hvac_in_rest": self.in_rest_period,
            "hvac_sequence_state": self.sequence_state,
        }
        # Publish to separate sensor node trace targets to ensure clean modular consumption loops
        self.client.publish("home/environment/inside", json.dumps(telemetry_packet))


if __name__ == "__main__":
    daemon = HvacHardwareDaemon()
    daemon.start()
