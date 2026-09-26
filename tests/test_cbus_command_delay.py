import sys
import asyncio
from collections import deque
from pathlib import Path

import pytest

from controllers import cbus_daemon


CMQTTD_ROOT = Path(__file__).resolve().parents[1] / "hardware" / "cmqttd"
if str(CMQTTD_ROOT) not in sys.path:
    sys.path.insert(0, str(CMQTTD_ROOT))

from cbus.daemon import cmqttd


def test_cbus_launcher_passes_configured_command_delay(tmp_path, monkeypatch):
    config_path = tmp_path / "config.ini"
    config_path.write_text(
        """
[MQTT]
broker = localhost
[CBUS]
host = 127.0.0.1
port = 2000
command_delay_ms = 200
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(cbus_daemon, "CONFIG_PATH", config_path)

    arguments = cbus_daemon._load_arguments()

    assert arguments[arguments.index("--command-delay-ms") + 1] == "200"


def test_cbus_command_delay_dispatches_commands_in_order_without_blocking(monkeypatch):
    command_loop = asyncio.new_event_loop()
    client = cmqttd.MqttClient(
        command_delay_seconds=0.2,
        command_loop=command_loop,
    )
    client._pending_commands = deque(
        [
            ("first", 23, True, 255, 0),
            ("second", 37, False, 0, 0),
        ]
    )
    client._command_task = object()
    dispatched = []
    delays = []

    async def record_delay(seconds):
        delays.append(seconds)

    monkeypatch.setattr(
        client,
        "_send_cbus_command",
        lambda *command: dispatched.append(command),
    )
    monkeypatch.setattr(cmqttd.asyncio, "sleep", record_delay)

    asyncio.run(client._dispatch_cbus_commands())

    assert dispatched == [
        ("first", 23, True, 255, 0),
        ("second", 37, False, 0, 0),
    ]
    assert delays == [pytest.approx(0.2)]
    command_loop.close()
