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

    # CBUS Application IDs (Common Clipsal/CGate applications)
    APP_LIGHTING = 56
    APP_BLINDS = 36
    APP_CLIMATE = 80
    APP_SECURITY = 4
    APP_IRRIGATION = 72

    def __init__(self):
        print(f"[INIT] Launching Subsystem. Platform Native Pi = {sys.platform != 'win32'}")

        cfg_manager = CBusConfigManager()
        self.config = cfg_manager.get_cbus_settings()
        self.broker_ip = cfg_manager.get_mqtt_broker()

        self.cbus_interface = NetworkCBUSInterface(
            host=self.config["host"], port=self.config["port"], timeout=self.config["timeout"]
        )
        self.device_manager = CBUSDeviceManager(self.cbus_interface)

        # Resolve project configuration path references safely
        xml_setting = self.config.get("xml_path")
        self.xml_path = Path(xml_setting) if xml_setting else Path(__file__).resolve().parent.parent / "cbus_project.xml"

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

        parser = CBusXMLParser(self.xml_path)
        devices = parser.parse_devices(app_mappings)

        if not devices:
            print("[WARN] Using static default hardcoded fallback devices.")
            devices = [
                {"name": "living_room_main", "app": self.APP_LIGHTING, "group": 1, "type": "light"},
                {"name": "living_room_dimmer", "app": self.APP_LIGHTING, "group": 2, "type": "dimmer"}
            ]

        # Register every parsed node cleanly
        for dev in devices:
            self.device_manager.register_device(
                name=dev["name"], application=dev["app"], group=dev["group"], device_type=dev["type"]
            )
        print(f"[SUCCESS] Ingested and registered {len(devices)} CBUS device tracking blocks.")

    def _sync_initial_states(self) -> None:
        """Requests full network indicators via checksum-verified bulk MMI frames based on cmqttd logic."""
        print("[SYNC] Querying C-Bus interface for live device network states...")

        devices = list(self.device_manager.devices.keys())
        status_updated = False
        loop_counter = 0

        if devices:
            while not status_updated and loop_counter < 3:
                # Trigger the verified bulk MMI snapshot request frame (\050038000100C2\r\n)
                print(f"[SYNC] Transmitting bulk snapshot request via cmqttd framework format...")
                self.device_manager.request_network_sync(self.APP_LIGHTING)

                # Give the 5500PC serial lines 1.5 seconds to return the stream response data
                time.sleep(1.5)

                # Drain the queue to see if our memory states populated successfully
                self.device_manager.process_incoming_messages()

                # Check our tracking metrics
                sample_device = self.device_manager.devices[devices[0]]
                if sample_device.current_state is None:
                    loop_counter += 1
                    time.sleep(1.0)
                else:
                    print("[SYNC SUCCESS] Real-time hardware snapshot compiled successfully.")
                    status_updated = True

    def start(self):
        """Initializes and runs the core telemetry loop engine."""
        print("[INIT] Connecting to CBUS interface...")
        if not self.device_manager.connect():
            print("[ERROR] Connection to CBUS interface failed. Exiting.")
            return

        # 1. Register devices with the manager first
        self._register_configured_devices()

        # 2. Configure and spin up the MQTT broker client connection
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

        # 3. Give the MQTT client a brief moment to finish its handshake and subscribe
        print("[INIT] Waiting briefly for MQTT subscription routing to complete...")
        time.sleep(1.0)

        # 4. Now that your listeners are active, trigger the network sync request
        self._sync_initial_states()

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
                raw_device_name = topic.split("/")[-1]

                # Match against registered devices case-insensitively
                device_name = None
                for registered_name in self.device_manager.devices.keys():
                    if registered_name.lower() == raw_device_name.lower():
                        device_name = registered_name
                        break

                if device_name:
                    command = payload.get("command", "ON")
                    value = payload.get("value")
                    success = self.device_manager.control_device(device_name, command, value)

                    result = {"device": device_name, "command": command, "value": value, "success": success, "timestamp": time.time()}
                    self.client.publish(f"home/cbus/status/{device_name}", json.dumps(result))
        except Exception as e:
            print(f"[MQTT ERROR] Failed processing payload: {e}")

    def _process_control_tick(self):
        """Processes network updates and streams unified, synchronized telemetry."""
        # 1. Drain the interface queue exclusively here to keep tracking variables safe
        messages = self.device_manager.process_incoming_messages()
        for message in messages:
            payload = {
                "application": message["application"],
                "group": message["group"],
                "command": message["command"],
                "value": message.get("value"),
                "timestamp": message["timestamp"]
            }
            self.client.publish("home/cbus/incoming", json.dumps(payload))

        # 2. Output states safely from memory instead of using the fetch_data hook
        if time.time() - self.last_heartbeat >= 30:
            # Loop through registered device objects natively without touching the socket link
            for dev_name, device in self.device_manager.devices.items():
                dev_data = {
                    "application": device.application,
                    "group": device.group,
                    "type": device.device_type,
                    "state": device.current_state, # Pull directly from memory structure
                    "last_update": device.last_update
                }
                self.client.publish(f"home/cbus/telemetry/{dev_name}", json.dumps(dev_data), retain=True)

            # Transmit heartbeat tracking payload
            heartbeat = {
                "status": "online",
                "device_count": len(self.device_manager.devices),
                "timestamp": time.time()
            }
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

# Resume the google session with "Let's resume the C-Bus integration using cmqttd"
