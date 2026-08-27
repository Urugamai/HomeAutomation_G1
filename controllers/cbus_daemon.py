import sys
import time
import json
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing. Run 'pip install paho-mqtt'.")
    sys.exit(1)

try:
    from hardware.cbus_interface import NetworkCBUSInterface, CBUSDeviceManager
except ImportError:
    print("[CRITICAL] CBUS interface module not found.")
    sys.exit(1)

# Import our modular additions
from cbus_xml_parser import CBusXMLParser
from cbus_config import CBusConfigManager


class CBUSHardwareDaemon:
    """Bridges dynamically discovered CBUS addresses into an active MQTT runtime."""

    APP_LIGHTING = 56
    APP_BLINDS = 36
    APP_CLIMATE = 80
    APP_SECURITY = 4
    APP_IRRIGATION = 72

    def __init__(self):
        print(f"[INIT] Launching Subsystem. Native Pi = {sys.platform != 'win32'}")

        cfg_manager = CBusConfigManager()
        self.config = cfg_manager.get_cbus_settings()
        self.broker_ip = cfg_manager.get_mqtt_broker()

        self.cbus_interface = NetworkCBUSInterface(
            host=self.config["host"], port=self.config["port"], timeout=self.config["timeout"]
        )
        self.device_manager = CBUSDeviceManager(self.cbus_interface)
        self._register_configured_devices()

        self.running = False
        self.last_heartbeat = time.time()

    def _register_configured_devices(self) -> None:
        """Registers configuration elements using the Toolkit parser or defaults."""
        app_mappings = {
            self.APP_LIGHTING: "light",
            self.APP_BLINDS: "blind",
            self.APP_CLIMATE: "climate",
            self.APP_SECURITY: "security",
            self.APP_IRRIGATION: "irrigation"
        }

        # Pull path string from ini config or use default workspace local file
        xml_setting = self.config.get("xml_path")
        xml_path = Path(xml_setting) if xml_setting else Path(__file__).resolve().parent.parent / "cbus_project.xml"

        # Try parsing from Toolkit file first
        parser = CBusXMLParser(xml_path)
        devices = parser.parse_devices(app_mappings)

        # Fallback to defaults if file is missing/broken
        if not devices:
            print("[WARN] Using static default hardcoded fallback devices.")
            devices = [
                {"name": "living_room_main", "app": self.APP_LIGHTING, "group": 1, "type": "light"},
                {"name": "living_room_dimmer", "app": self.APP_LIGHTING, "group": 2, "type": "dimmer"},
                {"name": "kitchen_main", "app": self.APP_LIGHTING, "group": 3, "type": "light"}
            ]

        for dev in devices:
            self.device_manager.register_device(
                name=dev["name"], application=dev["app"], group=dev["group"], device_type=dev["type"]
            )

    def start(self):
        """Initializes and runs the core telemetry loop engine."""
        print("[INIT] Connecting to CBUS interface...")
        if not self.device_manager.connect():
            print("[ERROR] Connection to CBUS interface failed. Exiting.")
            return

        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        try:
            self.client.connect(self.broker_ip, 1883, keepalive=60)
            self.client.loop_start()
            print(f"[MQTT] Connected to broker at {self.broker_ip}")
        except Exception as e:
            print(f"[NETWORK ERROR] Broker connection failed: {e}")
            self.device_manager.disconnect()
            return

        self.running = True
        print("[RUNNING] CBUS loop active. Scanning every 2 seconds.")

        try:
            while self.running:
                self._process_control_tick()
                time.sleep(2.0)
        except KeyboardInterrupt:
            print("[SHUTDOWN] Stopping daemon execution.")
        finally:
            self._cleanup()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        client.subscribe("home/cbus/command/#")
        client.subscribe("home/cbus/config")
        print("[MQTT] Subscribed to command endpoints.")

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode('utf-8'))
            if topic == "home/cbus/config":
                if "register_device" in payload:
                    dev = payload["register_device"]
                    self.device_manager.register_device(
                        name=dev["name"], application=dev["application"],
                        group=dev["group"], device_type=dev.get("type", "unknown")
                    )
            elif topic.startswith("home/cbus/command/"):
                device_name = topic.split("/")[-1]
                command = payload.get("command", "ON")
                value = payload.get("value")
                success = self.device_manager.control_device(device_name, command, value)

                result = {"device": device_name, "command": command, "value": value, "success": success, "timestamp": time.time()}
                self.client.publish(f"home/cbus/status/{device_name}", json.dumps(result))
        except Exception as e:
            print(f"[MQTT ERROR] Failed processing payload: {e}")

    def _process_control_tick(self):
        messages = self.device_manager.process_incoming_messages()
        for message in messages:
            payload = {
                "application": message["application"], "group": message["group"],
                "command": message["command"], "value": message.get("value"), "timestamp": message["timestamp"]
            }
            self.client.publish("home/cbus/incoming", json.dumps(payload))

        if time.time() - self.last_heartbeat >= 30:
            data = self.device_manager.fetch_data()
            for dev_name, dev_data in data["devices"].items():
                self.client.publish(f"home/cbus/telemetry/{dev_name}", json.dumps(dev_data), retain=True)

            heartbeat = {"status": "online", "device_count": len(data["devices"]), "timestamp": time.time()}
            self.client.publish("home/cbus/heartbeat", json.dumps(heartbeat))
            self.last_heartbeat = time.time()

    def _cleanup(self):
        print("[CLEANUP] Stopping interface tasks.")
        self.device_manager.disconnect()
        if hasattr(self, 'client'):
            self.client.loop_stop()
            self.client.disconnect()
        self.running = False


if __name__ == "__main__":
    daemon = CBUSHardwareDaemon()
    daemon.start()
