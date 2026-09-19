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

try:
    import RPi.GPIO as GPIO
    IS_RASPI = True
except ImportError:
    GPIO = None
    IS_RASPI = False

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing. Run 'pip install paho-mqtt'.")
    sys.exit(1)

from libraries.paho_compat import create_client
from libraries.environment_metrics import (
    OUTDOOR_ECOWITT_SOURCE,
    indoor_temperature_average,
)
from libraries.hvac_settings import HvacSettingsStore


class HvacHardwareDaemon:
    """
    Independent background loop driving real-time Raspberry Pi GPIO relays
    from temperature telemetry published by the living-area environment daemon.
    """
    RELAY_HEAT = 26  # Waveshare RPi Relay Board CH1, physical pin 37
    RELAY_COOL = 20  # Waveshare RPi Relay Board CH2, physical pin 38
    RELAY_FAN = 21  # Waveshare RPi Relay Board CH3, physical pin 40

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
        self.settings_store = HvacSettingsStore()
        self._load_persisted_settings()

        # Run State Machine Flags
        self.current_state = "OFF"  # Expected options: OFF, HEATING, COOLING
        self.sequence_state = "OFF"
        self.pending_state = None
        self.sequence_started_at = time.time()
        self.active_run_started_at = None
        self.in_rest_period = False
        self.rest_start_time = 0.0
        self.blind_pre_close_triggered = False
        self.latest_inside_temperature = None
        self.indoor_sensor_count = 0
        self.environment_sources = {}
        self.manual_target = None
        self.heater_relay_on = False
        self.cooler_relay_on = False
        self.fan_relay_on = False
        self.gpio_ready = False

        if IS_RASPI:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setwarnings(False)
                for pin in (self.RELAY_HEAT, self.RELAY_COOL, self.RELAY_FAN):
                    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
                self.gpio_ready = True
                self._write_relays("OFF")
            except Exception as e:
                print(f"[GPIO ERROR] Could not configure Waveshare relay board: {e}")
        else:
            print("[GPIO ERROR] RPi.GPIO is unavailable; relay outputs are disabled.")

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
        self.client.subscribe("home/hvac/command")
        self.client.subscribe("home/environment/#")

    def _on_message(self, client, userdata, msg):
        try:
            if msg.topic == "home/hvac/settings":
                payload = json.loads(msg.payload.decode("utf-8"))
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
                    try:
                        self.settings_store.save(self._settings_payload())
                    except OSError as error:
                        print(f"[SETTINGS ERROR] Unable to persist HVAC settings: {error}")
                print(
                    f"[SETTINGS UPDATED] Min: {self.t_min}°C | Max: {self.t_max}°C | "
                    f"Preheat: {self.fan_preheat_seconds}s | Postrun: {self.fan_postrun_seconds}s"
                )
            elif msg.topic == "home/hvac/command":
                payload = json.loads(msg.payload.decode("utf-8"))
                self._handle_manual_command(payload.get("action"))
            elif (
                msg.topic.startswith("home/environment/")
                and msg.topic not in (
                    "home/environment/inside",
                    "home/environment/forecast",
                )
            ):
                payload = json.loads(msg.payload.decode("utf-8"))
                self._record_environment_source(msg.topic, payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as e:
            print(f"[PARSE EXCEPTION] Bad configuration update payload structure: {e}")

    def _handle_manual_command(self, action):
        action = str(action or "").upper()
        if action not in ("HEATING", "COOLING", "FAN", "AUTO"):
            raise ValueError(f"Unsupported HVAC command: {action}")

        with self._settings_lock:
            if action == "AUTO":
                self.manual_target = None
                if self.sequence_state == "MANUAL_FAN":
                    self.sequence_state = "OFF"
                    self._write_relays("OFF")
                print("[MANUAL CONTROL] Returned HVAC control to automatic mode.")
            elif action == "FAN":
                if self.current_state in ("HEATING", "COOLING") or self.sequence_state in (
                    "PREHEAT",
                    "POSTRUN",
                ):
                    print("[MANUAL CONTROL] Fan cannot be turned off while HVAC sequencing requires it.")
                elif self.manual_target == "FAN":
                    self.manual_target = "OFF"
                    self.sequence_state = "OFF"
                    self._write_relays("OFF")
                else:
                    self.manual_target = "FAN"
                    self.current_state = "OFF"
                    self.sequence_state = "MANUAL_FAN"
                    self._write_relays("FAN")
            elif (
                self.current_state == action
                or self.manual_target == action
                or (
                    self.sequence_state == "PREHEAT"
                    and self.pending_state == action
                )
            ):
                self.manual_target = "OFF"
            else:
                self.manual_target = action
                if self.sequence_state == "MANUAL_FAN":
                    self.sequence_state = "OFF"
                    self._write_relays("OFF")

            self._process_control_tick_locked()

    def _record_environment_source(self, topic, payload):
        if topic == "home/environment/ecowitt":
            source_key = OUTDOOR_ECOWITT_SOURCE
        else:
            source_key = (
                payload.get("hostname")
                or payload.get("device_name")
                or topic.rsplit("/", 1)[-1]
            )
        self.environment_sources[source_key] = payload
        (
            self.latest_inside_temperature,
            self.indoor_sensor_count,
        ) = indoor_temperature_average(self.environment_sources)

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

    def _load_persisted_settings(self):
        settings = self.settings_store.load()
        if not settings:
            return
        self.t_min = settings["target_min"]
        self.t_max = settings["target_max"]
        self.fan_preheat_seconds = settings["fan_preheat_seconds"]
        self.fan_postrun_seconds = settings["fan_postrun_seconds"]
        self.min_run_seconds = settings["min_run_seconds"]
        self.max_run_seconds = settings["max_run_seconds"]
        self.rest_seconds = settings["rest_seconds"]

    def _settings_payload(self):
        return {
            "target_min": self.t_min,
            "target_max": self.t_max,
            "fan_preheat_seconds": self.fan_preheat_seconds,
            "fan_postrun_seconds": self.fan_postrun_seconds,
            "min_run_seconds": self.min_run_seconds,
            "max_run_seconds": self.max_run_seconds,
            "rest_seconds": self.rest_seconds,
        }

    def _write_relays(self, mode: str):
        """
        Commands the active-low Waveshare RPi Relay Board while enforcing
        mutually exclusive heating and cooling outputs.
        """
        if not self.gpio_ready:
            return

        try:
            # The Waveshare inputs are active-low. Drop both appliances first
            # so no transition can briefly energize heating and cooling together.
            GPIO.output(self.RELAY_HEAT, GPIO.HIGH)
            GPIO.output(self.RELAY_COOL, GPIO.HIGH)

            if mode == "HEATING":
                GPIO.output(self.RELAY_FAN, GPIO.LOW)
                GPIO.output(self.RELAY_HEAT, GPIO.LOW)
            elif mode == "COOLING":
                GPIO.output(self.RELAY_FAN, GPIO.LOW)
                GPIO.output(self.RELAY_COOL, GPIO.LOW)
            elif mode == "FAN":
                GPIO.output(self.RELAY_FAN, GPIO.LOW)
            else:
                GPIO.output(self.RELAY_FAN, GPIO.HIGH)

            self.heater_relay_on = mode == "HEATING"
            self.cooler_relay_on = mode == "COOLING"
            self.fan_relay_on = mode in ("HEATING", "COOLING", "FAN")
        except Exception as e:
            print(f"[GPIO ERROR] Failed writing Waveshare relay outputs: {e}")

    def _process_control_tick(self):
        with self._settings_lock:
            self._process_control_tick_locked()

    def _process_control_tick_locked(self):
        """Evaluates HVAC safety rules, time tracking metrics, and structural thresholds."""
        current_temp = self.latest_inside_temperature
        now = time.time()
        if self.manual_target == "FAN":
            self.current_state = "OFF"
            self.pending_state = None
            self.sequence_state = "MANUAL_FAN"
            if not self.fan_relay_on:
                self._write_relays("FAN")
            self._broadcast_status_telemetry(current_temp)
            return

        if current_temp is None:
            if self.current_state != "OFF" or self.sequence_state != "OFF":
                print("[SAFETY] No valid indoor temperature is available. Turning HVAC outputs off.")
                self.current_state = "OFF"
                self.sequence_state = "OFF"
                self.pending_state = None
                self.active_run_started_at = None
                self._write_relays("OFF")
            self._broadcast_status_telemetry(current_temp)
            return

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
        if self.manual_target in ("HEATING", "COOLING", "OFF"):
            return self.manual_target
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

    def _broadcast_status_telemetry(self, current_temp):
        """Pushes health data updates back out over the broker line to feed adaptive layouts."""
        telemetry_packet = {
            "temperature": current_temp,
            "indoor_sensor_count": self.indoor_sensor_count,
            "hvac_control_mode": "MANUAL" if self.manual_target is not None else "AUTO",
            "hvac_state": self.current_state,
            "hvac_in_rest": self.in_rest_period,
            "hvac_sequence_state": self.sequence_state,
            "heater_relay_on": self.heater_relay_on,
            "cooler_relay_on": self.cooler_relay_on,
            "fan_relay_on": self.fan_relay_on,
        }
        # Publish to separate sensor node trace targets to ensure clean modular consumption loops
        self.client.publish("home/environment/inside", json.dumps(telemetry_packet))


if __name__ == "__main__":
    daemon = HvacHardwareDaemon()
    daemon.start()
