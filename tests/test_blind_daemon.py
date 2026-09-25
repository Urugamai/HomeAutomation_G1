import json

import yaml

from controllers.blind_daemon import BlindAutomationDaemon


class RecordingMqttClient:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.messages.append((topic, json.loads(payload), qos, retain))


def write_settings(path):
    path.write_text(
        yaml.safe_dump(
            {
                "defaults": {
                    "close_below_lux": 50,
                    "open_above_lux": 50,
                    "open_after": "00:00",
                    "sunset_delay_minutes": 0,
                    "manual_hold_minutes": 60,
                    "automated_hold_minutes": 60,
                },
                "devices": {"G_STDY_B_W": {"address": 31}},
            }
        ),
        encoding="utf-8",
    )


def test_low_light_closes_configured_blind_via_cbus_mqtt(tmp_path):
    settings_path = tmp_path / "blind-settings.yml"
    state_path = tmp_path / "blind-state.json"
    write_settings(settings_path)
    daemon = BlindAutomationDaemon(settings_path, state_path)
    daemon.client = RecordingMqttClient()

    daemon._handle_environment({"outside_lux": 49})

    assert daemon.client.messages == [
        (
            "homeassistant/light/cbus_31/set",
            {"state": "ON", "brightness": 255, "transition": 0},
            1,
            False,
        )
    ]
    assert daemon.states["31"]["position"] == "CLOSED"


def test_manual_hold_persists_and_blocks_automation_after_restart(tmp_path, monkeypatch):
    settings_path = tmp_path / "blind-settings.yml"
    state_path = tmp_path / "blind-state.json"
    write_settings(settings_path)
    clock = [1_000.0]
    monkeypatch.setattr("controllers.blind_daemon.time.time", lambda: clock[0])
    daemon = BlindAutomationDaemon(settings_path, state_path)
    daemon.client = RecordingMqttClient()

    daemon._handle_cbus_state(
        "homeassistant/light/cbus_31/state",
        {"state": "OFF", "cbus_source_addr": 10},
    )

    restarted_daemon = BlindAutomationDaemon(settings_path, state_path)
    restarted_daemon.client = RecordingMqttClient()
    restarted_daemon._handle_environment({"outside_lux": 49})

    assert restarted_daemon.states["31"]["manual_hold_until"] == 4_600.0
    assert restarted_daemon.client.messages == []


def test_hvac_close_lock_prevents_open_until_auto_resets_holds(tmp_path, monkeypatch):
    settings_path = tmp_path / "blind-settings.yml"
    state_path = tmp_path / "blind-state.json"
    write_settings(settings_path)
    clock = [1_000.0]
    monkeypatch.setattr("controllers.blind_daemon.time.time", lambda: clock[0])
    daemon = BlindAutomationDaemon(settings_path, state_path)
    daemon.client = RecordingMqttClient()

    daemon._handle_blind_command({"action": "CLOSE", "reason": "HVAC_PRECOOL"})
    daemon._handle_environment({"outside_lux": 100})

    assert len(daemon.client.messages) == 1
    assert daemon.states["31"]["hvac_locked"] is True

    daemon._handle_blind_command({"action": "RESET_AUTOMATION_HOLDS"})

    assert daemon.states["31"]["hvac_locked"] is False
    assert daemon.client.messages[-1][1]["state"] == "OFF"
