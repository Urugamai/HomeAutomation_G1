import configparser
import json
import queue
import re
import socket
import sys
import time
from pathlib import Path

import yaml

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from libraries.paho_compat import create_client


CONFIG_PATH = project_root / "config" / "home-controller-host-config.yml"
BROKER_CONFIG_PATH = project_root / "config.ini"
QUEUE_TOPIC = "home/cbus/queued-command"
SET_TOPIC_PATTERN = re.compile(r"^homeassistant/light/cbus_(\d{1,3})/set$")


def load_broker_settings(config_path=BROKER_CONFIG_PATH):
    try:
        config = configparser.ConfigParser()
        if not config.read(config_path):
            raise RuntimeError(f"Unable to read MQTT configuration: {config_path}")
        broker = config.get("MQTT", "broker")
        port = config.getint("MQTT", "port", fallback=1883)
    except (configparser.Error, OSError, ValueError) as error:
        raise RuntimeError(f"Invalid MQTT broker configuration: {error}") from error
    if not broker:
        raise RuntimeError("MQTT broker must not be empty")
    if not 1 <= port <= 65_535:
        raise RuntimeError("MQTT port must be between 1 and 65535")
    return broker, port


def load_command_delay_seconds(config_path=CONFIG_PATH, hostname=None):
    hostname = hostname or socket.gethostname()
    try:
        with Path(config_path).open("r", encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file) or {}
        settings = config.get(hostname, {})
        delay_ms = int(settings.get("cbus-command-delay-ms", 200))
    except (OSError, TypeError, ValueError, yaml.YAMLError) as error:
        raise RuntimeError(f"Invalid C-Bus command delay configuration: {error}") from error
    if not 0 <= delay_ms <= 10_000:
        raise RuntimeError("cbus-command-delay-ms must be between 0 and 10000")
    return delay_ms / 1000


class CbusCommandDispatcher:
    """Serializes local C-Bus commands before they reach the stock cmqttd bridge."""

    def __init__(
        self,
        broker=None,
        delay_seconds=None,
        port=None,
        broker_config_path=BROKER_CONFIG_PATH,
    ):
        configured_broker, configured_port = load_broker_settings(broker_config_path)
        self.broker = broker or configured_broker
        self.port = configured_port if port is None else port
        if not 1 <= self.port <= 65_535:
            raise ValueError("MQTT port must be between 1 and 65535")
        self.delay_seconds = (
            load_command_delay_seconds() if delay_seconds is None else delay_seconds
        )
        self.client = None
        self.commands = queue.Queue()

    def start(self):
        self.client = create_client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect(self.broker, self.port, keepalive=60)
        self.client.loop_start()
        print(
            f"[CBUS DISPATCH] Connected to {self.broker}:{self.port}; "
            f"spacing commands by {self.delay_seconds * 1000:.0f} ms."
        )
        self._dispatch_commands()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        client.subscribe(QUEUE_TOPIC, qos=1)

    def _on_message(self, client, userdata, msg):
        try:
            request = json.loads(msg.payload.decode("utf-8"))
            topic = request["topic"]
            payload = request["payload"]
            if not isinstance(topic, str) or not SET_TOPIC_PATTERN.fullmatch(topic):
                raise ValueError("target topic must be a C-Bus light set topic")
            if not isinstance(payload, dict) or payload.get("state") not in ("ON", "OFF"):
                raise ValueError("payload must contain an ON or OFF state")
            self.commands.put((topic, payload, request.get("reason", "unspecified")))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            print(f"[CBUS DISPATCH ERROR] Rejected queued command: {error}")

    def _dispatch_commands(self):
        while True:
            topic, payload, reason = self.commands.get()
            self._publish_command(topic, payload, reason)
            time.sleep(self.delay_seconds)

    def _publish_command(self, topic, payload, reason):
        self.client.publish(topic, json.dumps(payload), qos=1, retain=False)
        print(f"[CBUS DISPATCH] {topic} state={payload['state']} reason={reason}")


if __name__ == "__main__":
    CbusCommandDispatcher().start()
