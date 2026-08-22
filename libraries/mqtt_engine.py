import sys
import json
import random
from PyQt6.QtCore import QObject, pyqtSignal, QTimer


class MqttTelemetryListener(QObject):
    """
    Unified cross-platform telemetry processor.
    Injects internal forecast set caching targets seamlessly into layout panels.
    """
    telemetry_received = pyqtSignal(dict)

    def __init__(self, broker="localhost", port=1883):
        super().__init__()
        self.broker = broker
        self.port = port
        self.is_windows = (sys.platform == "win32")
        self.client = None

        self.cached_data = {
            "inside_temp": 21.5,
            "outside_temp": 14.2,
            "battery_soc": 75,
            "battery_flow": 1200,
            "grid_flow": -450,
            "hvac_state": "OFF",
            "hvac_in_rest": False,
            # Placeholder structure keeping UI calls from dropping fields
            "forecast_set": [
                {"day_index": 0, "expected_min": None, "expected_max": 15.0, "summary": "Cloudy (Simulated)"},
                {"day_index": 1, "expected_min": 9.0, "expected_max": 17.0, "summary": "Mostly Sunny (Simulated)"}
            ]
        }

    def start(self):
        if self.is_windows:
            print("[ENV DETECTED] Windows 11 Node - Using Local UI Simulation Layout.")
            self.poll_timer = QTimer(self)
            self.poll_timer.timeout.connect(self._generate_simulated_telemetry)
            self.poll_timer.start(1000)
        else:
            print("[ENV DETECTED] Linux/Raspberry Pi Platform - Connecting to Active MQTT Broker.")
            self._initialize_linux_mqtt()

    def _generate_simulated_telemetry(self):
        self.cached_data["inside_temp"] = round(self.cached_data["inside_temp"] + random.uniform(-0.1, 0.1), 1)
        self.cached_data["outside_temp"] = round(self.cached_data["outside_temp"] + random.uniform(-0.1, 0.1), 1)
        self.cached_data["battery_flow"] = random.randint(-2500, 3500)
        self.cached_data["grid_flow"] = random.randint(-1500, 2500)
        self.cached_data["battery_soc"] = max(0, min(100, self.cached_data["battery_soc"] + random.randint(-1, 1)))
        self.telemetry_received.emit(self.cached_data.copy())

    def _initialize_linux_mqtt(self):
        try:
            import paho.mqtt.client as mqtt

            def on_connect(client, userdata, flags, rc, properties=None):
                client.subscribe("home/environment/#")
                client.subscribe("home/power/sigen")

            def on_message(client, userdata, msg):
                try:
                    topic = msg.topic
                    data = json.loads(msg.payload.decode('utf-8'))

                    if topic == "home/environment/inside":
                        self.cached_data["inside_temp"] = float(data.get("temperature", 0.0))
                    elif topic == "home/environment/forecast":
                        # Directly catch multi-day forecast loops emitted by bom_daemon
                        self.cached_data["forecast_set"] = data.get("forecast_set", [])
                    elif topic == "home/power/sigen":
                        self.cached_data["battery_soc"] = int(data.get("battery_soc", 0))
                        self.cached_data["battery_flow"] = int(data.get("battery_flow", 0))
                        self.cached_data["grid_flow"] = int(data.get("grid_flow", 0))

                    self.telemetry_received.emit(self.cached_data.copy())
                except Exception:
                    pass

            self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
            self.client.on_connect = on_connect
            self.client.on_message = on_message
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            print(f"[LINUX MQTT ERROR] Failed to bind local broker lines: {e}")

    def stop(self):
        if hasattr(self, 'poll_timer'):
            self.poll_timer.stop()
        if self.client:
            self.client.loop_stop()
