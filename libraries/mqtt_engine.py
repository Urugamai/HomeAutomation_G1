import datetime
import json
import sys
from PyQt6.QtCore import QObject, pyqtSignal

try:
    import paho.mqtt.client as mqtt

    PAHO_AVAILABLE = True
except ImportError:
    PAHO_AVAILABLE = False

from libraries.paho_compat import create_client


class MqttTelemetryListener(QObject):
    """Unified cross-platform telemetry processor capturing lux channels."""
    telemetry_received = pyqtSignal(dict)

    def __init__(self, broker="localhost", port=1883, location="rumpus"):
        super().__init__()
        self.broker = broker
        self.port = port
        self.location = location.strip("/") if location else None
        self.is_windows = (sys.platform == "win32")
        self.client = None

        self.cached_data = {
            "living_temp": 0.0,
            "living_lux": 0.0,  # FIXED: Added ambient room tracking cache
            "room_temp": 0.0,
            "room_humidity": 0.0,
            "room_pressure": 0.0,
            "room_source": "",
            "outside_temp": 0.0,
            "outside_lux": 0.0,  # FIXED: Added outdoor tracking cache
            "outside_humidity": 0.0,
            "solar_radiation": 0.0,
            "rain_rate": 0.0,
            "rain_today": 0.0,
            "rain_event": 0.0,
            "rain_week": 0.0,
            "rain_month": 0.0,
            "rain_year": 0.0,
            "rain_total": 0.0,
            "wind_speed": 0.0,
            "wind_gust": 0.0,
            "wind_direction": 0.0,
            "battery_soc": 0.0,
            "battery_flow": 0.0,
            "grid_flow": 0.0,
            "solar_power": 0.0,
            "solar_kwh_today": 0.0,
            "hvac_state": "OFF",
            "hvac_in_rest": False,
            "hvac_sequence_state": "OFF",
            "hvac_control_mode": "AUTO",
            "heater_relay_on": False,
            "cooler_relay_on": False,
            "fan_relay_on": False,
            "hvac_settings": {},
            "forecast_set": [],
            "environment_sources": {},
            "cbus_devices": {},
        }
        self._forecast_by_date = {}

    def start(self):
        if not PAHO_AVAILABLE: return

        self.client = create_client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        try:
            print(f"[MQTT CONNECTING] Establishing link to network broker at {self.broker}:{self.port}...")
            self.client.connect_async(self.broker, self.port, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            print(f"[MQTT EXCEPTION] Initialization failed: {e}")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        client.subscribe("home/environment/#")
        client.subscribe("home/hvac/settings")
        client.subscribe("home/power/sigen")
        client.subscribe("homeassistant/light/+/config")
        client.subscribe("homeassistant/light/+/state")

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8").strip()
            data = json.loads(payload) if payload else {}

            if topic == "home/hvac/settings":
                if not isinstance(data, dict):
                    raise ValueError("HVAC settings payload must be an object")
                self.cached_data["hvac_settings"] = data
            elif topic.startswith("homeassistant/light/cbus_"):
                self._process_cbus_message(topic, data)
                self.telemetry_received.emit(self.cached_data.copy())
                return

            if topic == "home/environment/ecowitt":
                self._record_environment_source(topic, data, "Ecowitt")
                self._update_cached_float(
                    "outside_temp", data, "outside_temp", "outdoor_temperature",
                    "outdoor_temp", "temperature")
                self._update_cached_float(
                    "outside_lux", data, "outside_lux", "outdoor_lux", "light_lux")
                self._update_cached_float(
                    "outside_humidity", data, "outside_humidity",
                    "outdoor_humidity", "humidity")
                self._update_cached_float(
                    "solar_radiation", data, "solar_radiation", "solarradiation")
                self._update_cached_float("rain_rate", data, "rain_rate", "rainrate")
                self._update_cached_float(
                    "rain_today", data, "rain_today", "dailyrain", "daily_rain")
                self._update_cached_float(
                    "rain_event", data, "rain_event", "eventrain", "event_rain")
                self._update_cached_float(
                    "rain_week", data, "rain_week", "weeklyrain", "weekly_rain")
                self._update_cached_float(
                    "rain_month", data, "rain_month", "monthlyrain", "monthly_rain")
                self._update_cached_float(
                    "rain_year", data, "rain_year", "yearlyrain", "yearly_rain")
                self._update_cached_float(
                    "rain_total", data, "rain_total", "totalrain", "total_rain")
                self._update_cached_float(
                    "wind_speed", data, "wind_speed", "wind_speed_kmh", "windspeed")
                self._update_cached_float("wind_gust", data, "wind_gust", "windgust")
                self._update_cached_float(
                    "wind_direction", data, "wind_direction", "winddir")
            elif topic == "home/environment/inside":
                self._update_hvac_status(data)
            elif topic == "home/environment/forecast":
                if "forecast_set" in data:
                    self._update_persistent_forecast_cache(data["forecast_set"])
            elif topic.startswith("home/environment/"):
                source_key = (
                    data.get("hostname")
                    or data.get("device_name")
                    or self._hostname_from_topic(topic)
                    or topic.rsplit("/", 1)[-1]
                )
                self._record_environment_source(topic, data, source_key)
                if self._is_local_environment_source(topic, data):
                    self._update_local_environment(data)
            elif topic == "home/power/sigen":
                self.cached_data["battery_soc"] = float(data.get("battery_soc", 0.0))
                self.cached_data["battery_flow"] = float(data.get("battery_flow", 0.0))
                self.cached_data["grid_flow"] = float(data.get("grid_flow", 0.0))
                self.cached_data["solar_power"] = float(data.get("solar_power", 0.0))
                self.cached_data["solar_kwh_today"] = float(data.get("solar_kwh_today", 0.0))

            self.telemetry_received.emit(self.cached_data.copy())
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            print(f"[MQTT DATA ERROR] Failed processing {msg.topic}: {error}")

    def _is_local_environment_source(self, topic, data):
        if not self.location:
            return topic == "home/environment/living"
        location = self.location.casefold()
        hostname = str(
            data.get("hostname") or data.get("device_name") or ""
        ).casefold()
        topic_location = self._hostname_from_topic(topic)
        return (
            hostname == location
            or topic_location is not None
            and topic_location.casefold() == location
        )

    def _update_local_environment(self, data):
        self._update_cached_float(
            "living_temp", data, "temperature", "room_temp", "living_temp"
        )
        self.cached_data["room_temp"] = self.cached_data["living_temp"]
        self._update_cached_float(
            "living_lux", data, "light_lux", "living_lux", "outside_lux"
        )
        self.cached_data["room_source"] = data.get(
            "hostname", data.get("device_name", self.location or "")
        )
        self._update_cached_float("room_humidity", data, "humidity")
        self._update_cached_float("room_pressure", data, "pressure")
        if "hvac_state" in data:
            self.cached_data["hvac_state"] = data["hvac_state"]
        if "hvac_in_rest" in data:
            self.cached_data["hvac_in_rest"] = bool(data["hvac_in_rest"])
        if "hvac_sequence_state" in data:
            self.cached_data["hvac_sequence_state"] = data["hvac_sequence_state"]

    def _update_hvac_status(self, data):
        self.cached_data["hvac_state"] = data.get(
            "hvac_state", self.cached_data["hvac_state"]
        )
        self.cached_data["hvac_in_rest"] = bool(
            data.get("hvac_in_rest", self.cached_data["hvac_in_rest"])
        )
        self.cached_data["hvac_sequence_state"] = data.get(
            "hvac_sequence_state", self.cached_data["hvac_sequence_state"]
        )
        self.cached_data["hvac_control_mode"] = data.get(
            "hvac_control_mode", self.cached_data["hvac_control_mode"]
        )
        for key in ("heater_relay_on", "cooler_relay_on", "fan_relay_on"):
            if key in data:
                self.cached_data[key] = bool(data[key])

    def _process_cbus_message(self, topic, data):
        parts = topic.split("/")
        if len(parts) < 4:
            return
        address_text = parts[2].removeprefix("cbus_")
        if not address_text.isdigit():
            return
        address = int(address_text)
        device = self.cached_data["cbus_devices"].setdefault(
            address,
            {"address": address, "name": f"C-Bus {address}"},
        )
        suffix = parts[3]
        if suffix == "config" and isinstance(data, dict):
            device["name"] = data.get("name") or device["name"]
        elif suffix == "state" and isinstance(data, dict):
            device["state"] = data.get("state", "OFF")
            device["brightness"] = data.get("brightness", 0)

    def set_cbus_device(self, address, is_on, brightness=None):
        if self.client is None:
            print("[CBUS ERROR] Cannot send command before MQTT connection is ready")
            return
        level = int(brightness if brightness is not None else (255 if is_on else 0))
        payload = {
            "state": "ON" if is_on and level > 0 else "OFF",
            "brightness": max(0, min(255, level)),
            "transition": 0,
        }
        topic = f"homeassistant/light/cbus_{int(address)}/set"
        self.client.publish(topic, json.dumps(payload), qos=1, retain=False)

    def set_hvac_settings(self, settings):
        if self.client is None:
            print("[HVAC ERROR] Cannot send settings before MQTT connection is ready")
            return
        self.client.publish(
            "home/hvac/settings",
            json.dumps(settings),
            qos=1,
            retain=True,
        )

    def set_hvac_command(self, command):
        if self.client is None:
            print("[HVAC ERROR] Cannot send command before MQTT connection is ready")
            return
        self.client.publish(
            "home/hvac/command",
            json.dumps(command),
            qos=1,
            retain=False,
        )

    @staticmethod
    def _get_float(data, *keys) -> float:
        for key in keys:
            value = data.get(key)
            if value is not None:
                return float(value)
        return 0.0

    def _update_cached_float(self, cache_key, data, *keys):
        for key in keys:
            if data.get(key) is not None:
                self.cached_data[cache_key] = float(data[key])
                return

    def _record_environment_source(self, topic, data, source_key):
        source = dict(data)
        source["topic"] = topic
        source["source_key"] = source_key
        source["hostname"] = (
            data.get("hostname", data.get("device_name", ""))
            if source_key == "Ecowitt"
            else data.get("hostname", data.get("device_name", source_key))
        )
        self.cached_data["environment_sources"][source_key] = source

    @staticmethod
    def _hostname_from_topic(topic):
        for prefix in ("home/environment/living/", "home/environment/"):
            if topic.startswith(prefix):
                suffix = topic[len(prefix):]
                if suffix and "/" not in suffix and suffix not in {
                    "ecowitt", "forecast", "living", "rumpus",
                }:
                    return suffix
        return None

    def _extract_forecast_date_key(self, item):
        timestamp = item.get("utc_timestamp")
        if timestamp:
            try:
                parsed = datetime.datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone()
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                pass
        day_index = item.get("day_index")
        if day_index is not None:
            try:
                return (datetime.date.today() + datetime.timedelta(days=int(day_index))).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                pass
        return None

    def _update_persistent_forecast_cache(self, incoming_forecasts):
        for incoming_item in incoming_forecasts:
            incoming_probability = next(
                (
                    incoming_item.get(key)
                    for key in (
                        "rain_probability",
                        "probability_of_precipitation",
                        "probability_of_rain",
                        "rain",
                    )
                    if incoming_item.get(key) is not None
                ),
                None,
            )

            date_key = self._extract_forecast_date_key(incoming_item)
            if not date_key:
                continue

            if date_key in self._forecast_by_date:
                cached = self._forecast_by_date[date_key]
                if "day_index" in incoming_item and incoming_item.get("day_index") is not None:
                    cached["day_index"] = incoming_item["day_index"]
                if incoming_item.get("utc_timestamp"):
                    cached["utc_timestamp"] = incoming_item["utc_timestamp"]
                if incoming_item.get("summary"):
                    cached["summary"] = incoming_item["summary"]
                if incoming_item.get("expected_min") is not None:
                    cached["expected_min"] = incoming_item["expected_min"]
                if incoming_item.get("expected_max") is not None:
                    cached["expected_max"] = incoming_item["expected_max"]
                if incoming_probability is not None:
                    cached["rain_probability"] = incoming_probability
            else:
                cached = incoming_item.copy()
                if incoming_probability is not None:
                    cached["rain_probability"] = incoming_probability
                self._forecast_by_date[date_key] = cached

        today_str = datetime.date.today().strftime("%Y-%m-%d")
        self._forecast_by_date = {
            k: v for k, v in self._forecast_by_date.items() if k >= today_str
        }

        sorted_forecasts = [
            self._forecast_by_date[k]
            for k in sorted(self._forecast_by_date.keys())
        ]
        for idx, item in enumerate(sorted_forecasts):
            if "day_index" not in item or item.get("day_index") is None:
                item["day_index"] = idx

        self.cached_data["forecast_set"] = sorted_forecasts

    def stop(self):
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
