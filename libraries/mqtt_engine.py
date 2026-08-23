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
    Natively tracks expanding multi-room temperature dictionary streams.
    """
    telemetry_received = pyqtSignal(dict)

    # Open libraries/mqtt_engine.py and update your cache setup block to read:

    def __init__(self, broker="localhost", port=1883):
        super().__init__()
        self.broker = broker
        self.port = port
        self.is_windows = (sys.platform == "win32")
        self.client = None

        # Central tracking telemetry cache matching exactly your UI variables
        self.cached_data = {
            "living_temp": 0.0,  # FIXED: Corrected default initializer key tracking element
            "outside_temp": 0.0,
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
        if not PAHO_AVAILABLE:
            print("[MQTT ERROR] Cannot establish loop. 'paho-mqtt' package is missing.")
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
            print("[MQTT INITIALIZED] Non-blocking interface loop armed successfully.")
        except Exception as e:
            print(f"[MQTT EXCEPTION] Initialization failed: {e}")

    def _service_mqtt_io(self):
        if self.client:
            self.client.loop_read()
            self.client.loop_write()
            self.client.loop_misc()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        print(f"[MQTT SUCCESS] Connected to {self.broker}. Arming system subscriptions.")
        # Subscribes to the broad wildcard tree to capture all rooms automatically
        client.subscribe("home/environment/#")
        client.subscribe("home/power/sigen")

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload_str = msg.payload.decode('utf-8').strip()

            # 1. Attempt to parse as a structured JSON payload first
            try:
                data = json.loads(payload_str)
            except json.JSONDecodeError:
                # Fallback: Handle single raw text numbers published directly to a sub-topic
                data = payload_str

            # 2. Extract and route metrics based on incoming topic destinations
            if topic == "home/environment/living" or topic == "SigEnergy/Home/living_temp":
                if isinstance(data, dict):
                    # Extracted from our structured environment_daemon dictionary
                    self.cached_data["living_temp"] = float(data.get("temperature", 0.0))
                else:
                    # Extracted from a raw fallback string payload
                    self.cached_data["living_temp"] = float(data)

            elif topic == "home/environment/rumpus":
                if isinstance(data, dict):
                    self.cached_data["rumpus_temp"] = float(data.get("temperature", 0.0))
                else:
                    self.cached_data["rumpus_temp"] = float(data)

            elif topic in ["home/environment/outside", "home/environment/ecowitt"]:
                if isinstance(data, dict):
                    self.cached_data["outside_temp"] = float(data.get("temperature", 0.0))
                else:
                    self.cached_data["outside_temp"] = float(data)

            elif topic == "home/environment/forecast":
                if isinstance(data, dict):
                    self.cached_data["forecast_set"] = data.get("forecast_set", [])

            elif topic == "home/power/sigen":
                if isinstance(data, dict):
                    self.cached_data["battery_soc"] = float(data.get("battery_soc", 0.0))
                    self.cached_data["battery_flow"] = float(data.get("battery_flow", 0.0))
                    self.cached_data["grid_flow"] = float(data.get("grid_flow", 0.0))
                    self.cached_data["solar_power"] = float(data.get("solar_power", 0.0))
                    self.cached_data["solar_kwh_today"] = float(data.get("solar_kwh_today", 0.0))

            # Push the updated data dictionary out to your UI screen components
            self.telemetry_received.emit(self.cached_data.copy())

        except Exception as e:
            print(f"[PARSE ERROR] Telemetry decoding failure on topic {msg.topic}: {e}")

    def stop(self):
        if hasattr(self, 'network_timer'):
            self.network_timer.stop()
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
