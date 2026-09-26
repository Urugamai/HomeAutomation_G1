import json

from controllers.cbus_command_dispatcher import (
    CbusCommandDispatcher,
    QUEUE_TOPIC,
    load_command_delay_seconds,
)


class RecordingMqttClient:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.messages.append((topic, json.loads(payload), qos, retain))


class Message:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")


def test_command_delay_loads_from_the_current_host_configuration(tmp_path):
    config_path = tmp_path / "home-controller-host-config.yml"
    config_path.write_text(
        "controller:\n  cbus-command-delay-ms: 200\n",
        encoding="utf-8",
    )

    assert load_command_delay_seconds(config_path, hostname="controller") == 0.2


def test_dispatcher_validates_then_publishes_real_cbus_set_command():
    dispatcher = CbusCommandDispatcher(delay_seconds=0.2)
    dispatcher.client = RecordingMqttClient()
    request = {
        "topic": "homeassistant/light/cbus_31/set",
        "payload": {"state": "OFF", "brightness": 0, "transition": 0},
        "reason": "low light",
    }

    dispatcher._on_message(None, None, Message(request))

    topic, payload, reason = dispatcher.commands.get_nowait()
    assert reason == "low light"
    dispatcher._publish_command(topic, payload, reason)

    assert dispatcher.client.messages == [
        (
            "homeassistant/light/cbus_31/set",
            request["payload"],
            1,
            False,
        )
    ]


def test_dispatcher_rejects_non_cbus_queue_targets(capsys):
    dispatcher = CbusCommandDispatcher(delay_seconds=0.2)

    dispatcher._on_message(
        None,
        None,
        Message({"topic": QUEUE_TOPIC, "payload": {"state": "ON"}}),
    )

    assert dispatcher.commands.empty()
    assert "Rejected queued command" in capsys.readouterr().out
