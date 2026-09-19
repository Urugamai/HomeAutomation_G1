import json

import pytest

import controllers.hvac_daemon as hvac_daemon
from libraries.hvac_settings import HvacSettingsStore


class _MqttClient:
    def publish(self, *args, **kwargs):
        pass


class _RecordingMqttClient:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload):
        self.messages.append((topic, json.loads(payload)))


def test_hvac_status_includes_commanded_relay_states():
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _RecordingMqttClient()

    controller._write_relays("HEATING")
    controller._broadcast_status_telemetry(19.0)

    topic, payload = controller.client.messages[-1]
    assert topic == "home/environment/inside"
    assert payload["heater_relay_on"] is True
    assert payload["cooler_relay_on"] is False
    assert payload["fan_relay_on"] is True


def test_hvac_settings_persist_to_and_load_from_nas_store(tmp_path):
    storage_path = tmp_path / "hvac_settings.json"
    saved = HvacSettingsStore(storage_path).save(
        {
            "target_min": 19.5,
            "target_max": 24.5,
            "fan_preheat_seconds": 60,
            "fan_postrun_seconds": 120,
            "min_run_seconds": 300,
            "max_run_seconds": 600,
            "rest_seconds": 300,
        }
    )

    assert HvacSettingsStore(storage_path).load() == saved


def test_hvac_fan_lead_minimum_run_and_postrun(monkeypatch):
    controller = hvac_daemon.HvacHardwareDaemon()
    commands = []
    temperatures = [19.0]
    clock = [0.0]
    monkeypatch.setattr(hvac_daemon.time, "time", lambda: clock[0])
    controller.client = _MqttClient()
    controller.latest_inside_temperature = temperatures[0]
    controller._write_relays = commands.append

    controller._process_control_tick()
    assert controller.sequence_state == "PREHEAT"
    assert commands[-1] == "FAN"

    clock[0] = 60.0
    controller._process_control_tick()
    assert controller.current_state == "HEATING"
    assert commands[-1] == "HEATING"

    temperatures[0] = 22.0
    controller.latest_inside_temperature = temperatures[0]
    clock[0] = 359.0
    controller._process_control_tick()
    assert controller.current_state == "HEATING"

    clock[0] = 360.0
    controller._process_control_tick()
    assert controller.sequence_state == "POSTRUN"
    assert commands[-1] == "FAN"

    clock[0] = 480.0
    controller._process_control_tick()
    assert controller.sequence_state == "OFF"
    assert commands[-1] == "OFF"


def test_hvac_maximum_run_starts_rest_period(monkeypatch):
    controller = hvac_daemon.HvacHardwareDaemon()
    commands = []
    clock = [0.0]
    monkeypatch.setattr(hvac_daemon.time, "time", lambda: clock[0])
    controller.client = _MqttClient()
    controller.latest_inside_temperature = 19.0
    controller._write_relays = commands.append

    controller.fan_preheat_seconds = 0
    controller.fan_postrun_seconds = 0
    controller._process_control_tick()
    assert controller.sequence_state == "HEATING"

    clock[0] = 600.0
    controller._process_control_tick()
    assert controller.in_rest_period
    assert commands[-1] == "OFF"
