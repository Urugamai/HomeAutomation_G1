import sys
import time
import json
import math
from datetime import datetime, time as dtime
from pathlib import Path
import configparser

try:
    import yaml
except ImportError:
    yaml = None

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing from active environment.")
    sys.exit(1)

from libraries.paho_compat import create_client

try:
    from pymodbus.client import ModbusTcpClient
    from pymodbus.exceptions import ModbusException

    MODBUS_AVAILABLE = True
except ImportError:
    MODBUS_AVAILABLE = False
    ModbusException = RuntimeError


class OcularChargerDaemon:
    """
    Background supervisor for the Ocular EV Charger.
    Uses grid-export feedback to absorb surplus solar after the home battery is full.
    """
    MIN_SOLAR_AMPS = 6
    MAX_SOLAR_AMPS = 32
    BATTERY_FULL_SOC = 99
    BATTERY_STOP_SOC = 60
    PHASE_VOLTAGE = 240
    PHASE_COUNT = 3
    OVERRIDE_AMPS = MAX_SOLAR_AMPS
    AMPS_CHANGE_INTERVAL_SECONDS = 10 * 60
    CHARGER_CURRENT_LIMIT_REGISTER = 200
    CHARGER_MODBUS_SLAVE = 1
    VEHICLE_SOC_REGISTER = None  # set in config/charger.yml once known
    VEHICLE_SOC_REGISTER_TYPE = "holding"
    VEHICLE_SOC_SCALE = 1.0
    CHEAP_POWER_ENABLED = True
    CHEAP_POWER_DAYS = (0, 1, 2, 3, 4)
    CHEAP_POWER_START = dtime(9, 0)
    CHEAP_POWER_END = dtime(17, 0)
    CHEAP_POWER_AMPS = MAX_SOLAR_AMPS
    CHEAP_POWER_MIN_SOC = 60
    DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    DEFAULT_CONFIG_PATH = project_root / "config" / "charger.yml"

    def __init__(self, config_path=None):
        print("[INIT] Launching Ocular EV Charger Controller Daemon...")
        self._load_settings(Path(config_path) if config_path else self.DEFAULT_CONFIG_PATH)
        self.broker_ip = self._get_config_str("MQTT", "broker", "localhost")
        self.charger_ip = self._get_config_str("CHARGER", "ip_address", "192.168.1.50")
        self.charger_port = int(self._get_config_str("CHARGER", "port", "502"))

        self.battery_soc = 50
        self.grid_flow_watts = 0
        self.solar_power_watts = 0
        self.current_charge_rate_amps = 0
        self.last_rate_change_at = None
        self.last_modbus_write_succeeded = False
        self.solar_charging_active = False
        self.override_enabled = False
        self.vehicle_soc = None

        if MODBUS_AVAILABLE:
            self.modbus_client = ModbusTcpClient(self.charger_ip, port=self.charger_port)
        else:
            self.modbus_client = None

    def _load_settings(self, path):
        config = {}
        if yaml is None:
            print("[CONFIG] PyYAML missing; using built-in charger defaults.")
        elif path.exists():
            try:
                with path.open("r", encoding="utf-8") as config_file:
                    config = yaml.safe_load(config_file) or {}
                if not isinstance(config, dict):
                    raise ValueError("top level must be a mapping")
            except (OSError, ValueError, yaml.YAMLError) as error:
                print(f"[CONFIG ERROR] {path.name}: {error}; using defaults.")
                config = {}

        def section(name):
            value = config.get(name)
            return value if isinstance(value, dict) else {}

        def setting(attr, values, key, convert):
            if key not in values:
                return
            try:
                setattr(self, attr, convert(values[key]))
            except (TypeError, ValueError) as error:
                print(f"[CONFIG ERROR] Ignoring {key}={values[key]!r}: {error}")

        solar, electrical = section("solar"), section("electrical")
        setting("MIN_SOLAR_AMPS", solar, "min-amps", int)
        setting("MAX_SOLAR_AMPS", solar, "max-amps", int)
        setting("BATTERY_FULL_SOC", solar, "battery-full-soc", float)
        setting("BATTERY_STOP_SOC", solar, "battery-stop-soc", float)
        setting("PHASE_VOLTAGE", electrical, "phase-voltage", float)
        setting("PHASE_COUNT", electrical, "phase-count", int)
        setting(
            "AMPS_CHANGE_INTERVAL_SECONDS",
            section("timing"),
            "amps-change-interval-seconds",
            float,
        )
        modbus = section("modbus")
        setting("CHARGER_CURRENT_LIMIT_REGISTER", modbus, "current-limit-register", int)
        setting("CHARGER_MODBUS_SLAVE", modbus, "slave", int)
        vehicle_soc = modbus.get("vehicle-soc")
        vehicle_soc = vehicle_soc if isinstance(vehicle_soc, dict) else {}
        setting("VEHICLE_SOC_REGISTER", vehicle_soc, "register", self._parse_optional_int)
        setting("VEHICLE_SOC_REGISTER_TYPE", vehicle_soc, "type", self._parse_register_type)
        setting("VEHICLE_SOC_SCALE", vehicle_soc, "scale", float)

        # Defaults that follow the (possibly overridden) max amps
        self.OVERRIDE_AMPS = self.MAX_SOLAR_AMPS
        self.CHEAP_POWER_AMPS = self.MAX_SOLAR_AMPS
        setting("OVERRIDE_AMPS", section("override"), "amps", int)

        cheap = section("cheap-power")
        setting("CHEAP_POWER_ENABLED", cheap, "enabled", self._parse_bool)
        setting("CHEAP_POWER_DAYS", cheap, "days", self._parse_days)
        setting("CHEAP_POWER_START", cheap, "start", self._parse_time)
        setting("CHEAP_POWER_END", cheap, "end", self._parse_time)
        setting("CHEAP_POWER_AMPS", cheap, "amps", int)
        setting("CHEAP_POWER_MIN_SOC", cheap, "min-battery-soc", float)

        for attr in ("OVERRIDE_AMPS", "CHEAP_POWER_AMPS"):
            if not self.MIN_SOLAR_AMPS <= getattr(self, attr) <= self.MAX_SOLAR_AMPS:
                print(f"[CONFIG ERROR] {attr} outside amp limits; using maximum.")
                setattr(self, attr, self.MAX_SOLAR_AMPS)

    @staticmethod
    def _parse_optional_int(value):
        return None if value is None else int(value)

    @staticmethod
    def _parse_register_type(value):
        value = str(value).strip().lower()
        if value not in ("holding", "input"):
            raise ValueError("must be holding or input")
        return value

    @staticmethod
    def _parse_bool(value):
        if not isinstance(value, bool):
            raise ValueError("must be true or false")
        return value

    @classmethod
    def _parse_days(cls, value):
        if not isinstance(value, (list, tuple)):
            raise ValueError("must be a list of day names")
        days = set()
        for item in value:
            name = str(item).strip().lower()[:3]
            if name not in cls.DAY_NAMES:
                raise ValueError(f"unknown day {item!r}")
            days.add(cls.DAY_NAMES.index(name))
        return tuple(sorted(days))

    @staticmethod
    def _parse_time(value):
        if isinstance(value, int):  # YAML reads 09:00 style times as base-60 ints
            if not 0 <= value < 24 * 60:
                raise ValueError("time out of range")
            return dtime(value // 60, value % 60)
        hour, minute = str(value).strip().split(":")
        return dtime(int(hour), int(minute))

    def _in_cheap_power_period(self, now):
        if not self.CHEAP_POWER_ENABLED:
            return False
        start, end, current = self.CHEAP_POWER_START, self.CHEAP_POWER_END, now.time()
        if start <= end:
            return now.weekday() in self.CHEAP_POWER_DAYS and start <= current < end
        # Window crosses midnight; the day listed is the day it starts on
        if current >= start:
            return now.weekday() in self.CHEAP_POWER_DAYS
        return (now.weekday() - 1) % 7 in self.CHEAP_POWER_DAYS and current < end

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
        client.subscribe("home/charger/override")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            if msg.topic == "home/power/sigen":
                if not isinstance(payload, dict):
                    raise ValueError("Sigen payload must be an object")
                self.battery_soc = float(payload.get("battery_soc", self.battery_soc))
                self.grid_flow_watts = float(
                    payload.get("grid_flow", self.grid_flow_watts)
                )
                self.solar_power_watts = float(
                    payload.get("solar_power", self.solar_power_watts)
                )
            elif msg.topic == "home/charger/override":
                self._set_override(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            print(f"[MQTT ERROR] Ignoring invalid charger message: {error}")

    def _evaluate_charging_logic(self):
        now = datetime.now()
        self._update_vehicle_soc()
        self._update_solar_charging_state()
        target_amps = self._target_amps(now)
        self._request_rate(target_amps)
        self._publish_status(now, target_amps)

    def _update_vehicle_soc(self):
        """Read the connected car's SOC from the charger; None when unavailable."""
        self.vehicle_soc = None
        if self.VEHICLE_SOC_REGISTER is None or not self.modbus_client:
            return
        try:
            if not self.modbus_client.connected and not self.modbus_client.connect():
                raise ConnectionError("Unable to connect to Ocular charger")
            read = (
                self.modbus_client.read_input_registers
                if self.VEHICLE_SOC_REGISTER_TYPE == "input"
                else self.modbus_client.read_holding_registers
            )
            # pymodbus 3.10+ renamed "slave" to "device_id"
            try:
                response = read(
                    address=self.VEHICLE_SOC_REGISTER,
                    count=1,
                    device_id=self.CHARGER_MODBUS_SLAVE,
                )
            except TypeError:
                response = read(
                    address=self.VEHICLE_SOC_REGISTER,
                    count=1,
                    slave=self.CHARGER_MODBUS_SLAVE,
                )
            if response is None or (
                hasattr(response, "isError") and response.isError()
            ):
                raise RuntimeError("Charger rejected vehicle SOC read")
            soc = response.registers[0] * self.VEHICLE_SOC_SCALE
            if 0 <= soc <= 100:
                self.vehicle_soc = soc
        except (ConnectionError, OSError, RuntimeError, IndexError, ModbusException) as error:
            print(f"[MODBUS ERROR] Unable to read vehicle SOC: {error}")

    def _set_override(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("enabled"), bool):
            raise ValueError("Charger override payload requires a boolean enabled field")
        enabled = payload["enabled"]
        if enabled == self.override_enabled:
            return
        self.override_enabled = enabled
        print(f"[COMMAND] Charger override {'enabled' if enabled else 'disabled'}.")
        self._request_rate(self._target_amps(), force=True)
        self._publish_status(datetime.now(), self._target_amps())

    def _update_solar_charging_state(self):
        if self.solar_charging_active:
            if self.battery_soc < self.BATTERY_STOP_SOC:
                self.solar_charging_active = False
                print(
                    f"[AUTOMATION] Battery SOC {self.battery_soc:.1f}% is below "
                    f"{self.BATTERY_STOP_SOC}%; stopping solar EV charging."
                )
        elif self.battery_soc >= self.BATTERY_FULL_SOC:
            self.solar_charging_active = True
            print(
                f"[AUTOMATION] Battery SOC {self.battery_soc:.1f}% reached "
                f"{self.BATTERY_FULL_SOC}%; enabling solar EV charging."
            )

    def _target_amps(self, now=None):
        if self.override_enabled:
            return self.OVERRIDE_AMPS
        if (
            self._in_cheap_power_period(now or datetime.now())
            and self.battery_soc >= self.CHEAP_POWER_MIN_SOC
        ):
            return self.CHEAP_POWER_AMPS
        if not self.solar_charging_active:
            return 0

        watts_per_amp = self.PHASE_VOLTAGE * self.PHASE_COUNT
        exported_watts = -self.grid_flow_watts
        if (
            self.current_charge_rate_amps == 0
            and exported_watts < self.MIN_SOLAR_AMPS * watts_per_amp
        ):
            return 0
        export_adjustment_amps = math.floor(exported_watts / watts_per_amp)
        return min(
            self.MAX_SOLAR_AMPS,
            max(
                self.MIN_SOLAR_AMPS,
                self.current_charge_rate_amps + export_adjustment_amps,
            ),
        )

    def _request_rate(self, target_amps, force=False):
        if target_amps == self.current_charge_rate_amps:
            return
        now = time.time()
        if (
            not force
            and self.last_rate_change_at is not None
            and now - self.last_rate_change_at < self.AMPS_CHANGE_INTERVAL_SECONDS
        ):
            return
        if self._write_modbus_rate(target_amps):
            self.current_charge_rate_amps = target_amps
            self.last_rate_change_at = now

    def _publish_status(self, now, target_amps):
        payload = {
            "timestamp": now.timestamp(),
            "state": "Charging" if target_amps > 0 else "Off",
            "target_amps": target_amps,
            "current_amps": self.current_charge_rate_amps,
            "grid_flow_watts": self.grid_flow_watts,
            "solar_power_watts": self.solar_power_watts,
            "battery_soc": self.battery_soc,
            "vehicle_soc": self.vehicle_soc,
            "is_override": self.override_enabled,
            "solar_charging_active": self.solar_charging_active,
            "modbus_write_succeeded": self.last_modbus_write_succeeded,
            "limits": {
                "minimum_solar_amps": self.MIN_SOLAR_AMPS,
                "maximum_solar_amps": self.MAX_SOLAR_AMPS,
                "override_amps": self.OVERRIDE_AMPS,
                "battery_full_soc": self.BATTERY_FULL_SOC,
                "battery_stop_soc": self.BATTERY_STOP_SOC,
                "watts_per_amp": self.PHASE_VOLTAGE * self.PHASE_COUNT,
                "minimum_start_export_watts": (
                    self.MIN_SOLAR_AMPS * self.PHASE_VOLTAGE * self.PHASE_COUNT
                ),
                "rate_change_interval_seconds": self.AMPS_CHANGE_INTERVAL_SECONDS,
                "cheap_power_enabled": self.CHEAP_POWER_ENABLED,
                "cheap_power_days": [self.DAY_NAMES[day] for day in self.CHEAP_POWER_DAYS],
                "cheap_power_start": self.CHEAP_POWER_START.strftime("%H:%M"),
                "cheap_power_end": self.CHEAP_POWER_END.strftime("%H:%M"),
                "cheap_power_amps": self.CHEAP_POWER_AMPS,
                "cheap_power_min_battery_soc": self.CHEAP_POWER_MIN_SOC,
            },
            "cheap_power_active": self._in_cheap_power_period(now),
        }
        try:
            self.mqtt_client.publish(
                "home/charger/status",
                json.dumps(payload),
                qos=1,
                retain=True,
            )
        except AttributeError:
            pass

    def _write_modbus_rate(self, amps: int) -> bool:
        if amps != 0 and not self.MIN_SOLAR_AMPS <= amps <= self.MAX_SOLAR_AMPS:
            raise ValueError(
                f"Charger current must be 0 A or {self.MIN_SOLAR_AMPS}-"
                f"{self.MAX_SOLAR_AMPS} A"
            )
        if not self.modbus_client:
            self.last_modbus_write_succeeded = False
            return False
        try:
            if not self.modbus_client.connected:
                if not self.modbus_client.connect():
                    raise ConnectionError("Unable to connect to Ocular charger")
            # pymodbus 3.10+ renamed "slave" to "device_id"
            try:
                response = self.modbus_client.write_register(
                    address=self.CHARGER_CURRENT_LIMIT_REGISTER,
                    value=amps,
                    device_id=self.CHARGER_MODBUS_SLAVE,
                )
            except TypeError:
                response = self.modbus_client.write_register(
                    address=self.CHARGER_CURRENT_LIMIT_REGISTER,
                    value=amps,
                    slave=self.CHARGER_MODBUS_SLAVE,
                )
            if response is None or (
                hasattr(response, "isError") and response.isError()
            ):
                raise RuntimeError(f"Charger rejected {amps} A current limit")
            self.last_modbus_write_succeeded = True
            print(f"[MODBUS] Set Ocular charge-current limit to {amps} A.")
            return True
        except (ConnectionError, OSError, RuntimeError, ModbusException) as error:
            self.last_modbus_write_succeeded = False
            print(f"[MODBUS ERROR] Unable to set charger current limit: {error}")
            return False


if __name__ == "__main__":
    daemon = OcularChargerDaemon()
    daemon.start()
