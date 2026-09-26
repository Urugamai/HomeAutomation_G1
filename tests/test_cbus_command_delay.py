import sys
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


def test_cbus_command_delay_waits_for_the_remaining_interval(monkeypatch):
    client = cmqttd.MqttClient(command_delay_seconds=0.2)
    client._last_cbus_command_at = 10.0
    clock = iter((10.05, 10.25))
    delays = []
    monkeypatch.setattr(cmqttd.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(cmqttd.time, "sleep", delays.append)

    client._wait_for_command_slot()

    assert delays == [pytest.approx(0.15)]
    assert client._last_cbus_command_at == 10.25
