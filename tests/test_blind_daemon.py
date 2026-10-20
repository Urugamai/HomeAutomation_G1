import datetime
import json

import yaml

from controllers.blind_daemon import BlindAutomationDaemon


class RecordingMqttClient:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.messages.append((topic, json.loads(payload), qos, retain))


def summer_time(hour):
    return datetime.datetime(2026, 12, 21, hour, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=11)))


def write_settings(path):
    path.write_text(
        yaml.safe_dump(
            {
                "location": {"latitude": -37.868, "longitude": 144.832},
                "defaults": {
                    "close_below_w_m2": 50,
                    "open_above_w_m2": 100,
                    "open_after": "00:00",
                    "sunset_delay_minutes": 0,
                    "manual_hold_minutes": 60,
                    "automated_hold_minutes": 60,
                    "closed_state": "OFF",
                },
                "devices": {"G_STDY_B_W": {"address": 31}},
            }
        ),
        encoding="utf-8",
    )


def test_low_light_closes_configured_blind_via_cbus_mqtt(tmp_path, capsys):
    settings_path = tmp_path / "blind-settings.yml"
    state_path = tmp_path / "blind-state.json"
    write_settings(settings_path)
    daemon = BlindAutomationDaemon(settings_path, state_path)
    daemon.client = RecordingMqttClient()

    daemon._handle_environment({"light_w_m2": 49})

    assert daemon.client.messages == [
        (
            "home/cbus/queued-command",
            {
                "topic": "homeassistant/light/cbus_31/set",
                "payload": {"state": "OFF", "brightness": 0, "transition": 0},
                "reason": (
                    "outside_w_m2=49.0 below close_below_w_m2=50.0; "
                    "dusk delay=0m elapsed"
                ),
            },
            1,
            False,
        )
    ]
    assert daemon.states["31"]["position"] == "CLOSED"
    assert (
        "reason=outside_w_m2=49.0 below close_below_w_m2=50.0; "
        "dusk delay=0m elapsed" in capsys.readouterr().out
    )


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
    restarted_daemon._handle_environment({"light_w_m2": 49})

    assert restarted_daemon.states["31"]["manual_hold_until"] == 4_600.0
    assert restarted_daemon.client.messages == []


def test_home_controller_command_uses_manual_hold(tmp_path, monkeypatch):
    settings_path = tmp_path / "blind-settings.yml"
    state_path = tmp_path / "blind-state.json"
    write_settings(settings_path)
    clock = [1_000.0]
    monkeypatch.setattr("controllers.blind_daemon.time.time", lambda: clock[0])
    daemon = BlindAutomationDaemon(settings_path, state_path)
    daemon.client = RecordingMqttClient()
    daemon._state_for(31)["automated_hold_until"] = 1_100.0

    daemon._handle_queued_command(
        {
            "source": "home-controller",
            "topic": "homeassistant/light/cbus_31/set",
            "payload": {"state": "OFF"},
        }
    )

    assert daemon.states["31"]["position"] == "CLOSED"
    assert daemon.states["31"]["manual_hold_until"] == 4_600.0

    clock[0] = 1_101.0
    daemon._handle_environment({"light_w_m2": 100})

    assert daemon.client.messages == []


def test_low_light_respects_manual_or_automated_hold(tmp_path):
    settings_path = tmp_path / "blind-settings.yml"
    state_path = tmp_path / "blind-state.json"
    write_settings(settings_path)
    daemon = BlindAutomationDaemon(settings_path, state_path)
    daemon.client = RecordingMqttClient()
    state = daemon._state_for(31)
    state["position"] = "OPEN"
    state["manual_hold_until"] = float("inf")
    state["automated_hold_until"] = float("inf")

    daemon._handle_environment({"light_w_m2": 0})

    assert daemon.client.messages == []
    assert state["position"] == "OPEN"


def test_cbus_off_state_is_treated_as_closed_for_configured_relay_polarity(tmp_path):
    settings_path = tmp_path / "blind-settings.yml"
    state_path = tmp_path / "blind-state.json"
    write_settings(settings_path)
    daemon = BlindAutomationDaemon(settings_path, state_path)

    daemon._handle_cbus_state("homeassistant/light/cbus_31/state", {"state": "OFF"})

    assert daemon.states["31"]["position"] == "CLOSED"


def test_hvac_close_lock_prevents_open_until_auto_resets_holds(tmp_path, monkeypatch):
    monkeypatch.setattr(BlindAutomationDaemon, "_now", staticmethod(lambda: summer_time(15)))
    settings_path = tmp_path / "blind-settings.yml"
    state_path = tmp_path / "blind-state.json"
    write_settings(settings_path)
    clock = [1_000.0]
    monkeypatch.setattr("controllers.blind_daemon.time.time", lambda: clock[0])
    daemon = BlindAutomationDaemon(settings_path, state_path)
    daemon.client = RecordingMqttClient()

    daemon._handle_blind_command({"action": "CLOSE", "reason": "HVAC_PRECOOL"})
    daemon._handle_environment({"light_w_m2": 100})

    assert len(daemon.client.messages) == 1
    assert daemon.states["31"]["hvac_locked"] is True

    daemon._handle_blind_command({"action": "RESET_AUTOMATION_HOLDS"})

    assert daemon.states["31"]["hvac_locked"] is False
    assert daemon.client.messages[-1][1]["payload"]["state"] == "ON"


def test_hvac_close_skips_shutters(tmp_path, monkeypatch):
    monkeypatch.setattr(BlindAutomationDaemon, "_now", staticmethod(lambda: summer_time(15)))
    settings_path = tmp_path / "blind-settings.yml"
    write_settings(settings_path)
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["devices"]["G_LIVNG_S_W"] = {"address": 32}
    settings_path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    daemon = BlindAutomationDaemon(settings_path, tmp_path / "blind-state.json")
    daemon.client = RecordingMqttClient()

    daemon._handle_blind_command({"action": "CLOSE", "reason": "HVAC_PRECOOL"})

    topics = [m[1]["topic"] for m in daemon.client.messages]
    assert topics == ["homeassistant/light/cbus_31/set"]
    assert not daemon.states.get("32", {}).get("hvac_locked", False)


def test_hvac_close_only_closes_windows_the_sun_is_on(tmp_path, monkeypatch):
    settings_path = tmp_path / "blind-settings.yml"
    write_settings(settings_path)
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["devices"] = {"1_SIT_B_N": {"address": 13}, "1_LNG_B_WL": {"address": 29}}
    settings_path.write_text(yaml.safe_dump(settings), encoding="utf-8")

    def closed_at(hour):
        monkeypatch.setattr(
            BlindAutomationDaemon, "_now", staticmethod(lambda: summer_time(hour))
        )
        daemon = BlindAutomationDaemon(settings_path, tmp_path / f"state{hour}.json")
        daemon.client = RecordingMqttClient()
        daemon._handle_blind_command({"action": "CLOSE", "reason": "HVAC_PRECOOL"})
        return sorted(m[1]["topic"] for m in daemon.client.messages)

    assert closed_at(10) == []
    assert closed_at(13) == ["homeassistant/light/cbus_13/set"]
    assert closed_at(15) == [
        "homeassistant/light/cbus_13/set",
        "homeassistant/light/cbus_29/set",
    ]
    assert closed_at(17) == ["homeassistant/light/cbus_29/set"]
    assert closed_at(21) == []


def test_hvac_lockout_applies_only_to_blinds_it_closed(tmp_path, monkeypatch):
    settings_path = tmp_path / "blind-settings.yml"
    write_settings(settings_path)
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["devices"] = {"1_SIT_B_N": {"address": 13}, "1_LNG_B_WL": {"address": 29}}
    settings_path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    hour = [13]
    monkeypatch.setattr(
        BlindAutomationDaemon, "_now", staticmethod(lambda: summer_time(hour[0]))
    )
    daemon = BlindAutomationDaemon(settings_path, tmp_path / "state.json")
    daemon.client = RecordingMqttClient()

    daemon._handle_blind_command({"action": "CLOSE", "reason": "HVAC_PRECOOL"})

    assert daemon.states["13"]["hvac_locked"] is True
    assert not daemon.states.get("29", {}).get("hvac_locked", False)
    assert len(daemon.client.messages) == 1

    hour[0] = 17
    daemon._handle_environment({"light_w_m2": 500})

    assert daemon.states["29"]["hvac_locked"] is True
    assert daemon.states["13"]["hvac_locked"] is False
    assert [m[1]["topic"] for m in daemon.client.messages[:2]] == [
        "homeassistant/light/cbus_13/set",
        "homeassistant/light/cbus_29/set",
    ]


def test_hvac_lock_released_when_sun_leaves_window(tmp_path, monkeypatch):
    settings_path = tmp_path / "blind-settings.yml"
    write_settings(settings_path)
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["devices"] = {"1_SIT_B_N": {"address": 13}}
    settings_path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    hour = [12]
    monkeypatch.setattr(
        BlindAutomationDaemon, "_now", staticmethod(lambda: summer_time(hour[0]))
    )
    daemon = BlindAutomationDaemon(settings_path, tmp_path / "state.json")
    daemon.client = RecordingMqttClient()
    daemon._handle_blind_command({"action": "CLOSE", "reason": "HVAC_PRECOOL"})
    assert daemon.states["13"]["hvac_locked"] is True

    hour[0] = 20
    daemon._handle_environment({"light_w_m2": 0})

    assert daemon.states["13"]["hvac_locked"] is False


def test_midnight_clears_all_holds_and_hvac_locks(tmp_path, monkeypatch):
    settings_path = tmp_path / "blind-settings.yml"
    write_settings(settings_path)
    day = [datetime.datetime(2026, 12, 21, 23, 0, tzinfo=datetime.timezone.utc)]
    monkeypatch.setattr(BlindAutomationDaemon, "_now", staticmethod(lambda: day[0]))
    daemon = BlindAutomationDaemon(settings_path, tmp_path / "state.json")
    daemon.client = RecordingMqttClient()
    daemon._handle_environment({"light_w_m2": 500})
    state = daemon._state_for(31)
    state.update(hvac_locked=True, manual_hold_until=9e12, automated_hold_until=9e12)
    daemon.hvac_close_reason = "HVAC_PRECOOL"

    day[0] = datetime.datetime(2026, 12, 22, 0, 1, tzinfo=datetime.timezone.utc)
    daemon._handle_environment({"light_w_m2": 500})

    assert state["hvac_locked"] is False
    assert state["manual_hold_until"] == 0.0
    assert state["automated_hold_until"] == 0.0
    assert daemon.hvac_close_reason is None


def test_releasing_hvac_locks_preserves_manual_hold(tmp_path, monkeypatch):
    settings_path = tmp_path / "blind-settings.yml"
    state_path = tmp_path / "blind-state.json"
    write_settings(settings_path)
    clock = [1_000.0]
    monkeypatch.setattr("controllers.blind_daemon.time.time", lambda: clock[0])
    daemon = BlindAutomationDaemon(settings_path, state_path)
    daemon.client = RecordingMqttClient()
    state = daemon._state_for(31)
    state["position"] = "CLOSED"
    state["hvac_locked"] = True
    state["manual_hold_until"] = 4_600.0
    daemon.latest_outside_w_m2 = 100

    daemon._handle_blind_command({"action": "RELEASE_HVAC_LOCKS"})

    assert state["hvac_locked"] is False
    assert state["manual_hold_until"] == 4_600.0
    assert daemon.client.messages == []
