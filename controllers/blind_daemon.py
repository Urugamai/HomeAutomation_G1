import datetime
import json
import os
import sys
import time
from pathlib import Path
import configparser

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    import yaml
except ImportError:
    yaml = None

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing. Run 'pip install paho-mqtt'.")
    sys.exit(1)

from libraries.paho_compat import create_client


class BlindAutomationDaemon:
    """Applies persistent, per-device blind and shutter automation policies."""

    SETTINGS_PATH = project_root / "config" / "blind-settings.yml"
    STATE_PATH = Path("/mnt/WatsonHome/blind_automation_state.json")
    STATE_VERSION = 2

    def __init__(self, settings_path=None, state_path=None):
        print("[INIT] Launching Autonomous Blind Controller Daemon...")
        self.broker_ip = self._load_broker_config()
        self.settings_path = Path(settings_path or self.SETTINGS_PATH)
        self.state_path = Path(state_path or self.STATE_PATH)
        self.devices = self._load_settings()
        self.states, self.dark_since = self._load_state()
        self.latest_outside_lux = None
        self.client = None

    def _load_broker_config(self) -> str:
        config_path = project_root / "config.ini"
        if config_path.exists():
            try:
                config = configparser.ConfigParser()
                config.read(str(config_path))
                return config.get("MQTT", "broker", fallback="localhost")
            except configparser.Error as error:
                print(f"[CONFIG ERROR] Unable to read MQTT configuration: {error}")
        return "localhost"

    def _load_settings(self):
        if yaml is None:
            raise RuntimeError("PyYAML is required for blind-settings.yml")
        try:
            with self.settings_path.open("r", encoding="utf-8") as settings_file:
                settings = yaml.safe_load(settings_file) or {}
        except OSError as error:
            raise RuntimeError(
                f"Unable to load blind settings from {self.settings_path}: {error}"
            ) from error
        except yaml.YAMLError as error:
            raise RuntimeError(
                f"Invalid blind settings in {self.settings_path}: {error}"
            ) from error

        defaults = settings.get("defaults", {})
        configured_devices = settings.get("devices", {})
        if not isinstance(defaults, dict) or not isinstance(configured_devices, dict):
            raise RuntimeError("blind-settings.yml requires defaults and devices mappings")

        devices = {}
        for label, configured_policy in configured_devices.items():
            if not isinstance(label, str) or not isinstance(configured_policy, dict):
                raise RuntimeError("Each blind settings entry must be a label and mapping")
            policy = {**defaults, **configured_policy}
            parts = label.upper().split("_")
            if len(parts) < 3 or parts[2] not in ("B", "S"):
                raise RuntimeError(
                    f"{label} is not a blind or shutter C-Bus group label"
                )
            try:
                address = int(policy["address"])
                open_after = datetime.time.fromisoformat(str(policy["open_after"]))
                for setting in (
                    "close_below_lux",
                    "open_above_lux",
                    "sunset_delay_minutes",
                    "manual_hold_minutes",
                    "automated_hold_minutes",
                ):
                    policy[setting] = float(policy[setting])
                policy["closed_state"] = str(policy["closed_state"]).upper()
            except (KeyError, TypeError, ValueError) as error:
                raise RuntimeError(f"Invalid settings for {label}: {error}") from error
            if not 0 <= address <= 255:
                raise RuntimeError(f"{label} has an invalid C-Bus group address: {address}")
            if any(value < 0 for value in policy.values() if isinstance(value, float)):
                raise RuntimeError(f"{label} has a negative automation duration or lux value")
            if policy["closed_state"] not in ("ON", "OFF"):
                raise RuntimeError(f"{label} closed_state must be ON or OFF")
            if address in devices:
                raise RuntimeError(f"Duplicate C-Bus group address in blind settings: {address}")
            policy["label"] = label
            policy["open_after"] = open_after
            devices[address] = policy
        if not devices:
            raise RuntimeError("blind-settings.yml does not configure any blind or shutter")
        return devices

    def _load_state(self):
        if not self.state_path.is_file():
            return {}, None
        try:
            with self.state_path.open("r", encoding="utf-8") as state_file:
                payload = json.load(state_file)
            if payload.get("version") != self.STATE_VERSION:
                print("[STATE] Resetting stale blind state after relay polarity update.")
                return {}, None
            states = payload.get("devices", {})
            if not isinstance(states, dict):
                raise ValueError("devices must be a mapping")
            dark_since = payload.get("dark_since")
            return states, float(dark_since) if dark_since is not None else None
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            print(f"[STATE ERROR] Ignoring invalid blind state file: {error}")
            return {}, None

    def _save_state(self):
        payload = {
            "version": self.STATE_VERSION,
            "devices": self.states,
            "dark_since": self.dark_since,
        }
        temporary_path = self.state_path.with_suffix(".tmp")
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with temporary_path.open("w", encoding="utf-8") as state_file:
                json.dump(payload, state_file, separators=(",", ":"))
                state_file.flush()
                os.fsync(state_file.fileno())
            os.replace(temporary_path, self.state_path)
        except OSError as error:
            print(f"[STATE ERROR] Unable to save blind automation state: {error}")
            try:
                temporary_path.unlink()
            except OSError:
                pass

    def _state_for(self, address):
        return self.states.setdefault(
            str(address),
            {
                "position": "UNKNOWN",
                "manual_hold_until": 0.0,
                "automated_hold_until": 0.0,
                "hvac_locked": False,
            },
        )

    def start(self):
        self.client = create_client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        connected = False
        while not connected:
            try:
                self.client.connect(self.broker_ip, 1883, keepalive=60)
                self.client.loop_start()
                connected = True
                print(f"[MQTT] Blind Daemon connected to broker ({self.broker_ip}).")
            except Exception as error:
                print(
                    f"[NETWORK DELAY] Blind Daemon broker unavailable: {error}. "
                    "Retrying in 5 seconds..."
                )
                time.sleep(5.0)

        print("[RUNNING] Per-device blind automation is armed.")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("[SHUTDOWN] Terminating Blind Automation Daemon.")
            self.client.loop_stop()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        print(f"[MQTT] Blind Daemon bound to broker ({self.broker_ip}).")
        self.client.subscribe("home/blinds/command")
        self.client.subscribe("home/environment/ecowitt")
        self.client.subscribe("homeassistant/light/+/state")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            if msg.topic == "home/blinds/command":
                self._handle_blind_command(payload)
            elif msg.topic == "home/environment/ecowitt":
                self._handle_environment(payload)
            elif msg.topic.startswith("homeassistant/light/cbus_") and msg.topic.endswith(
                "/state"
            ):
                self._handle_cbus_state(msg.topic, payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            print(f"[PARSE ERROR] Blind Daemon rejected MQTT message: {error}")

    def _handle_blind_command(self, payload):
        action = str(payload.get("action", "")).upper()
        if action == "CLOSE":
            print(f"[COMMAND] HVAC requested blind close: {payload.get('reason', 'UNKNOWN')}")
            for address in self.devices:
                state = self._state_for(address)
                state["hvac_locked"] = True
                self._move(address, "CLOSED", automated=False, force=True)
            self._save_state()
        elif action == "RESET_AUTOMATION_HOLDS":
            print("[COMMAND] Clearing blind automation holds at HVAC AUTO request.")
            for address in self.devices:
                state = self._state_for(address)
                state["manual_hold_until"] = 0.0
                state["automated_hold_until"] = 0.0
                state["hvac_locked"] = False
            self._save_state()
            if self.latest_outside_lux is not None:
                self._evaluate_lux(self.latest_outside_lux)
        else:
            raise ValueError(f"Unsupported blind command action: {action}")

    def _handle_environment(self, payload):
        outside_lux = payload.get("outside_lux", payload.get("light_lux"))
        if outside_lux is None:
            return
        self.latest_outside_lux = float(outside_lux)
        self._evaluate_lux(self.latest_outside_lux)

    def _handle_cbus_state(self, topic, payload):
        address_text = topic.removeprefix("homeassistant/light/cbus_").removesuffix(
            "/state"
        )
        if not address_text.isdigit():
            return
        address = int(address_text)
        if address not in self.devices:
            return
        position = (
            "CLOSED"
            if str(payload.get("state", "")).upper()
            == self.devices[address]["closed_state"]
            else "OPEN"
        )
        state = self._state_for(address)
        state["position"] = position
        if payload.get("cbus_source_addr") is not None:
            policy = self.devices[address]
            state["manual_hold_until"] = time.time() + policy["manual_hold_minutes"] * 60
            print(
                f"[MANUAL] {policy['label']} moved to {position}; "
                f"holding automation for {policy['manual_hold_minutes']:.0f} minutes."
            )
        self._save_state()

    def _evaluate_lux(self, outside_lux):
        now = time.time()
        is_dark_for_any_device = any(
            outside_lux < policy["close_below_lux"]
            for policy in self.devices.values()
        )
        if is_dark_for_any_device and self.dark_since is None:
            self.dark_since = now
        elif not is_dark_for_any_device:
            self.dark_since = None

        for address, policy in self.devices.items():
            state = self._state_for(address)
            if outside_lux < policy["close_below_lux"]:
                delay_seconds = policy["sunset_delay_minutes"] * 60
                if now - self.dark_since >= delay_seconds:
                    self._move(address, "CLOSED", automated=True)
                continue

            if (
                state["hvac_locked"]
                or now < state["manual_hold_until"]
                or now < state["automated_hold_until"]
            ):
                continue

            if (
                outside_lux > policy["open_above_lux"]
                and datetime.datetime.now().time() >= policy["open_after"]
            ):
                self._move(address, "OPEN", automated=True)
        self._save_state()

    def _move(self, address, target_position, automated, force=False):
        state = self._state_for(address)
        if not force and state["position"] == target_position:
            return
        policy = self.devices[address]
        payload = {
            "state": (
                policy["closed_state"]
                if target_position == "CLOSED"
                else "OFF" if policy["closed_state"] == "ON" else "ON"
            ),
            "brightness": (
                255
                if (
                    target_position == "CLOSED" and policy["closed_state"] == "ON"
                )
                or (
                    target_position == "OPEN" and policy["closed_state"] == "OFF"
                )
                else 0
            ),
            "transition": 0,
        }
        self.client.publish(
            f"homeassistant/light/cbus_{address}/set",
            json.dumps(payload),
            qos=1,
            retain=False,
        )
        state["position"] = target_position
        if automated:
            state["automated_hold_until"] = (
                time.time() + policy["automated_hold_minutes"] * 60
            )
        print(f"[AUTOMATION] {policy['label']} -> {target_position}")


if __name__ == "__main__":
    BlindAutomationDaemon().start()
