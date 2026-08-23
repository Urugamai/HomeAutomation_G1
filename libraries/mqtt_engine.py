import sys
import json
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

try:
    import paho.mqtt.client as mqtt

    PAHO_AVAILABLE = True
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing from active environment.")
    PAHO_AVAILABLE = False


class MqttTelemetryListener(QObject):
    """
    Unified cross-platform telemetry processor.
    Implements a persistent weather cache to lock in valid multi-day metrics.
    """
    telemetry_received = pyqtSignal(dict)

    def __init__(self, broker="localhost", port=1883):
        super().__init__()
        self.broker = broker
        self.port = port
        self.is_windows = (sys.platform == "win32")
        self.client = None

        # Central tracking telemetry cache matching exactly your UI variables
        self.cached_data = {
            "living_temp": 0.0,
            "outside_temp": 0.0,
            "battery_soc": 0.0,
            "battery_flow": 0.0,
            "grid_flow": 0.0,
            "solar_power": 0.0,
            "solar_kwh_today": 0.0,
            "hvac_state": "OFF",
            "hvac_in_rest": False,
            # Initial baseline forecast structure
            "forecast_set": [
                {"day_index": 0, "expected_min": None, "expected_max": None, "summary": "Loading..."},
                {"day_index": 1, "expected_min": None, "expected_max": None, "summary": "Loading..."}
            ]
        }

    def start(self):
        if not PAHO_AVAILABLE:
            return

        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        try:
            print(f"[MQTT CONNECTING] Establishing link to network broker at {self.broker}:{self.port}...")
            self.client.connect_async(self.broker, self.port, keepalive=60)
            self.client.loop_start()

            self.network_timer = QTimer(self)
            self.network_timer.timeout.connect(self._service_mqtt_io)
            self.network_timer.start(50)
        except Exception as e:
            print(f"[MQTT EXCEPTION] Initialization failed: {e}")

    def _service_mqtt_io(self):
        if self.client:
            self.client.loop_read()
            self.client.loop_write()
            self.client.loop_misc()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        print(f"[MQTT SUCCESS] Connected to {self.broker}. Arming system subscriptions.")
        client.subscribe("home/environment/#")
        client.subscribe("home/power/sigen")

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload_str = msg.payload.decode('utf-8').strip()

            try:
                data = json.loads(payload_str)
            except json.JSONDecodeError:
                data = payload_str

            if topic == "home/environment/living":
                if isinstance(data, dict):
                    self.cached_data["living_temp"] = float(data.get("temperature", 0.0))
                else:
                    self.cached_data["living_temp"] = float(data)
            elif topic == "home/environment/rumpus":
                if isinstance(data, dict):
                    self.cached_data["rumpus_temp"] = float(data.get("temperature", 0.0))
            elif topic in ["home/environment/outside", "home/environment/ecowitt"]:
                if isinstance(data, dict):
                    self.cached_data["outside_temp"] = float(data.get("temperature", 0.0))
                else:
                    self.cached_data["outside_temp"] = float(data)

            elif topic == "home/environment/forecast":
                if isinstance(data, dict) and "forecast_set" in data:
                    # FIXED: Merge data intelligently to lock in values if they go missing
                    self._update_persistent_forecast_cache(data["forecast_set"])

            elif topic == "home/power/sigen":
                if isinstance(data, dict):
                    self.cached_data["battery_soc"] = float(data.get("battery_soc", 0.0))
                    self.cached_data["battery_flow"] = float(data.get("battery_flow", 0.0))
                    self.cached_data["grid_flow"] = float(data.get("grid_flow", 0.0))
                    self.cached_data["solar_power"] = float(data.get("solar_power", 0.0))
                    self.cached_data["solar_kwh_today"] = float(data.get("solar_kwh_today", 0.0))

            self.telemetry_received.emit(self.cached_data.copy())
        except Exception as e:
            print(f"[PARSE ERROR] Telemetry decoding failure: {e}")

    def _update_persistent_forecast_cache(self, incoming_forecasts):
        """Processes weather entries line-by-line to prevent null values from wiping out valid records."""
        for incoming_item in incoming_forecasts:
            day_idx = incoming_item.get("day_index")

            # Find the matching entry inside our master memory cache
            for cached_item in self.cached_data["forecast_set"]:
                if cached_item["day_index"] == day_idx:
                    # 1. Update text summaries and timestamps unconditionally
                    if incoming_item.get("summary"):
                        cached_item["summary"] = incoming_item["summary"]
                    if incoming_item.get("utc_timestamp"):
                        cached_item["utc_timestamp"] = incoming_item["utc_timestamp"]

                    # 2. FIXED: Lock in temperature values. Only overwrite if the new data is not None.
                    if incoming_item.get("expected_min") is not None:
                        cached_item["expected_min"] = incoming_item["expected_min"]
                    if incoming_item.get("expected_max") is not None:
                        cached_item["expected_max"] = incoming_item["expected_max"]

    def stop(self):
        if hasattr(self, 'network_timer'):
            self.network_timer.stop()
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
