import sys
import time
import json
import configparser
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing. Run 'pip install paho-mqtt'.")
    sys.exit(1)

# Import CBUS interface from hardware module
try:
    from hardware.cbus_interface import NetworkCBUSInterface, CBUSDeviceManager
except ImportError:
    print("[CRITICAL] CBUS interface module not found.")
    sys.exit(1)


class CBUSHardwareDaemon:
    """
    Independent background loop driving CBUS home automation integration.
    Bridges CBUS lighting and control systems with MQTT for unified automation.
    """
    
    # CBUS Application IDs (Common Clipsal/CGate applications)
    APP_LIGHTING = 56      # Lighting control
    APP_BLINDS = 36        # Blind control
    APP_CLIMATE = 80       # Climate control
    APP_SECURITY = 4       # Security system
    APP_IRRIGATION = 72    # Irrigation control
    
    def __init__(self):
        print(f"[INIT] Launching CBUS Daemon Subsystem. Platform Native Pi = {sys.platform != 'win32'}")
        
        # Load configuration values
        self.config = self._load_cbus_config()
        self.broker_ip = self._load_broker_config()
        
        # Initialize CBUS interface
        self.cbus_interface = NetworkCBUSInterface(
            host=self.config.get("host", "192.168.2.2"),
            port=self.config.get("port", 2000),
            timeout=self.config.get("timeout", 1.0)
        )
        
        self.device_manager = CBUSDeviceManager(self.cbus_interface)
        
        # Register configured devices
        self._register_configured_devices()
        
        # State tracking
        self.running = False
        self.last_heartbeat = time.time()
        
    def _load_cbus_config(self) -> dict:
        """Load CBUS-specific configuration from config.ini."""
        config_path = Path(__file__).resolve().parent.parent / "config.ini"
        cbus_config = {
            "host": "192.168.2.2",
            "port": 2000,
            "timeout": 1.0
        }
        
        if config_path.exists():
            try:
                config = configparser.ConfigParser()
                config.read(str(config_path))
                if config.has_section("CBUS"):
                    cbus_config["host"] = config.get("CBUS", "host", fallback="192.168.2.2")
                    cbus_config["port"] = config.getint("CBUS", "port", fallback=2000)
                    cbus_config["timeout"] = config.getfloat("CBUS", "timeout", fallback=1.0)
            except Exception as e:
                print(f"[CONFIG ERROR] Failed to load CBUS config: {e}")
        
        return cbus_config
    
    def _load_broker_config(self) -> str:
        """Load MQTT broker configuration."""
        config_path = Path(__file__).resolve().parent.parent / "config.ini"
        if config_path.exists():
            try:
                config = configparser.ConfigParser()
                config.read(str(config_path))
                return config.get("MQTT", "broker", fallback="localhost")
            except Exception:
                pass
        return "localhost"
    
    def _register_configured_devices(self) -> None:
        """Register CBUS devices from configuration or use defaults."""
        # Default device configuration - can be extended to load from config.ini
        default_devices = [
            {"name": "living_room_main", "app": self.APP_LIGHTING, "group": 1, "type": "light"},
            {"name": "living_room_dimmer", "app": self.APP_LIGHTING, "group": 2, "type": "dimmer"},
            {"name": "kitchen_main", "app": self.APP_LIGHTING, "group": 3, "type": "light"},
            {"name": "bedroom_main", "app": self.APP_LIGHTING, "group": 4, "type": "light"},
            {"name": "hallway_main", "app": self.APP_LIGHTING, "group": 5, "type": "light"},
            {"name": "blinds_living", "app": self.APP_BLINDS, "group": 10, "type": "blind"},
            {"name": "blinds_bedroom", "app": self.APP_BLINDS, "group": 11, "type": "blind"},
        ]
        
        for device in default_devices:
            self.device_manager.register_device(
                name=device["name"],
                application=device["app"],
                group=device["group"],
                device_type=device["type"]
            )
    
    def start(self):
        """Initialize CBUS interface, MQTT connection, and start control loop."""
        print("[INIT] Connecting to CBUS interface...")
        if not self.device_manager.connect():
            print("[ERROR] Failed to connect to CBUS interface. Exiting.")
            return
        
        # Initialize MQTT client
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        
        try:
            self.client.connect(self.broker_ip, 1883, keepalive=60)
            self.client.loop_start()
            print(f"[MQTT] Connected to broker at {self.broker_ip}")
        except Exception as e:
            print(f"[NETWORK ERROR] Broker handshake failed: {e}")
            self.device_manager.disconnect()
            return
        
        self.running = True
        print("[RUNNING] CBUS automation loop active. Processing cycles every 2 seconds.")
        
        try:
            while self.running:
                self._process_control_tick()
                time.sleep(2.0)  # Process every 2 seconds
        except KeyboardInterrupt:
            print("[SHUTDOWN] Terminating CBUS daemon.")
        finally:
            self._cleanup()
    
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Subscribe to MQTT topics for CBUS control."""
        print(f"[MQTT] Connected. Subscribing to CBUS control topics...")
        # Subscribe to CBUS control topics
        client.subscribe("home/cbus/command/#")
        client.subscribe("home/cbus/config")
    
    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT commands for CBUS control."""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode('utf-8'))
            
            if topic == "home/cbus/config":
                self._handle_config_command(payload)
            elif topic.startswith("home/cbus/command/"):
                device_name = topic.split("/")[-1]
                self._handle_device_command(device_name, payload)
                
        except Exception as e:
            print(f"[MQTT ERROR] Failed to process message: {e}")
    
    def _handle_config_command(self, payload: dict) -> None:
        """Handle configuration updates for CBUS devices."""
        if "register_device" in payload:
            device_info = payload["register_device"]
            self.device_manager.register_device(
                name=device_info["name"],
                application=device_info["application"],
                group=device_info["group"],
                device_type=device_info.get("type", "unknown")
            )
            print(f"[CONFIG] Registered new device: {device_info['name']}")
    
    def _handle_device_command(self, device_name: str, payload: dict) -> None:
        """Handle control commands for specific CBUS devices."""
        command = payload.get("command", "ON")
        value = payload.get("value")
        
        print(f"[COMMAND] Controlling device {device_name}: {command} -> {value}")
        
        success = self.device_manager.control_device(device_name, command, value)
        
        # Publish result
        result = {
            "device": device_name,
            "command": command,
            "value": value,
            "success": success,
            "timestamp": time.time()
        }
        self.client.publish(f"home/cbus/status/{device_name}", json.dumps(result))
    
    def _process_control_tick(self):
        """Main control loop tick - process incoming CBUS messages and publish telemetry."""
        # Process incoming CBUS messages
        messages = self.device_manager.process_incoming_messages()
        
        # Publish any incoming CBUS messages to MQTT
        for message in messages:
            self._publish_cbus_message(message)
        
        # Publish periodic telemetry
        if time.time() - self.last_heartbeat >= 30:  # Every 30 seconds
            self._publish_telemetry()
            self.last_heartbeat = time.time()
    
    def _publish_cbus_message(self, message: dict) -> None:
        """Publish an incoming CBUS message to MQTT."""
        payload = {
            "application": message["application"],
            "group": message["group"],
            "command": message["command"],
            "value": message.get("value"),
            "timestamp": message["timestamp"]
        }
        self.client.publish("home/cbus/incoming", json.dumps(payload))
        print(f"[CBUS IN] App={message['application']}, Group={message['group']}, Cmd={message['command']}")
    
    def _publish_telemetry(self) -> None:
        """Publish current state of all CBUS devices."""
        data = self.device_manager.fetch_data()
        
        # Publish device states
        for device_name, device_data in data["devices"].items():
            self.client.publish(
                f"home/cbus/telemetry/{device_name}",
                json.dumps(device_data),
                retain=True
            )
        
        # Publish system heartbeat
        heartbeat = {
            "status": "online",
            "device_count": len(data["devices"]),
            "timestamp": time.time()
        }
        self.client.publish("home/cbus/heartbeat", json.dumps(heartbeat))
        print("[HEARTBEAT] CBUS system status published")
    
    def _cleanup(self) -> None:
        """Clean up resources on shutdown."""
        print("[CLEANUP] Disconnecting CBUS interface...")
        self.device_manager.disconnect()
        
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
        
        self.running = False


if __name__ == "__main__":
    daemon = CBUSHardwareDaemon()
    daemon.start()
