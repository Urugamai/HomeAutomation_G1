import paho.mqtt.client as mqtt
import json
import configparser
from typing import Callable, Any

class MqttController:
    def __init__(self, config_path: str = "config.ini"):
        config = configparser.ConfigParser()
        config.read(config_path)
        
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.broker = config.get("MQTT", "broker", fallback="localhost")
        self.port = config.getint("MQTT", "port", fallback=1883)
        self.callbacks = {}

    def connect(self):
        self.client.on_message = self._on_message
        self.client.connect(self.broker, self.port)
        self.client.loop_start()

    def publish(self, topic: str, payload: Any, retain: bool = False):
        msg = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)
        self.client.publish(topic, msg, retain=retain)

    def subscribe(self, topic: str, callback: Callable[[str, dict], None]):
        self.callbacks[topic] = callback
        self.client.subscribe(topic)

    def _on_message(self, client, userdata, message):
        topic = message.topic
        if topic in self.callbacks:
            try:
                payload = json.loads(message.payload.decode())
            except json.JSONDecodeError:
                payload = message.payload.decode()
            self.callbacks[topic](topic, payload)
