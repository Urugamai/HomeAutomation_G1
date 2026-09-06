import sys
import json
from PyQt6.QtCore import QObject, pyqtSignal

try:
    import paho.mqtt.client as mqtt

    PAHO_AVAILABLE = True
except ImportError:
    PAHO_AVAILABLE = False


class MqttTelemetryListener(QObject):
    """Unified cross-platform telemetry processor capturing lux channels."""
    telemetry_received = pyqtSignal(dict)

    def __init__(self, broker="localhost", port=1883):
        super().__init__()
        self.broker = broker
        self.port = port
        self.is_windows = (sys.platform == "win32")
        self.client = None

        self.cached_data = {
            "living_temp": 0.0,
            "living_lux": 0.0,  # FIXED: Added ambient room tracking cache
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
            "forecast_set": []
        }

    def start(self):
        if not PAHO_AVAILABLE: return

        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
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
        client.subscribe("home/power/sigen")

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            data = json.loads(msg.payload.decode('utf-8').strip())

            if topic == "home/environment/living":
                self.cached_data["living_temp"] = float(data.get("temperature", 0.0))
                self.cached_data["living_lux"] = float(data.get("light_lux", 0.0))
                self.cached_data["hvac_state"] = data.get("hvac_state", "OFF")
                self.cached_data["hvac_in_rest"] = bool(data.get("hvac_in_rest", False))
            elif topic == "home/environment/ecowitt":
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
            elif topic == "home/environment/forecast":
                if "forecast_set" in data:
                    self._update_persistent_forecast_cache(data["forecast_set"])
            elif topic == "home/power/sigen":
                self.cached_data["battery_soc"] = float(data.get("battery_soc", 0.0))
                self.cached_data["battery_flow"] = float(data.get("battery_flow", 0.0))
                self.cached_data["grid_flow"] = float(data.get("grid_flow", 0.0))
                self.cached_data["solar_power"] = float(data.get("solar_power", 0.0))
                self.cached_data["solar_kwh_today"] = float(data.get("solar_kwh_today", 0.0))

            self.telemetry_received.emit(self.cached_data.copy())
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            print(f"[MQTT DATA ERROR] Failed processing {msg.topic}: {error}")

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

    def _update_persistent_forecast_cache(self, incoming_forecasts):
        for incoming_item in incoming_forecasts:
            day_idx = incoming_item.get("day_index")
            found = False
            for cached_item in self.cached_data["forecast_set"]:
                if cached_item["day_index"] == day_idx:
                    if incoming_item.get("summary"): cached_item["summary"] = incoming_item["summary"]
                    if incoming_item.get("expected_min") is not None: cached_item["expected_min"] = incoming_item["expected_min"]
                    if incoming_item.get("expected_max") is not None: cached_item["expected_max"] = incoming_item["expected_max"]
                    if incoming_item.get("rain_probability") is not None: cached_item["rain_probability"] = incoming_item["rain_probability"]
                    found = True
                    break
            if not found:
                self.cached_data["forecast_set"].append(incoming_item)

    def stop(self):
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
