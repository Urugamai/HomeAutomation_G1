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


class _Message:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = json.dumps(payload).encode("utf-8")


class _FakeGpio:
    BCM = "BCM"
    OUT = "OUT"
    HIGH = 1
    LOW = 0

    def __init__(self):
        self.outputs = {}

    def setmode(self, mode):
        assert mode == self.BCM

    def setwarnings(self, enabled):
        assert enabled is False

    def setup(self, pin, mode, initial):
        assert mode == self.OUT
        self.outputs[pin] = initial

    def output(self, pin, value):
        self.outputs[pin] = value


def test_waveshare_relay_mapping_uses_active_low_gpio(monkeypatch):
    gpio = _FakeGpio()
    monkeypatch.setattr(hvac_daemon, "GPIO", gpio)
    monkeypatch.setattr(hvac_daemon, "IS_RASPI", True)

    controller = hvac_daemon.HvacHardwareDaemon()
    controller._write_relays("HEATING")

    assert gpio.outputs == {
        controller.RELAY_HEAT: gpio.LOW,
        controller.RELAY_COOL: gpio.HIGH,
        controller.RELAY_FAN: gpio.LOW,
    }
    assert controller.heater_relay_on is True
    assert controller.cooler_relay_on is False
    assert controller.fan_relay_on is True


def test_hvac_controls_from_the_average_of_indoor_sources():
    controller = hvac_daemon.HvacHardwareDaemon()

    controller._on_message(
        None,
        None,
        _Message("home/environment/ecowitt", {"temperature": 12.0}),
    )
    controller._on_message(
        None,
        None,
        _Message("home/environment/living", {"hostname": "living", "temperature": 20.0}),
    )
    controller._on_message(
        None,
        None,
        _Message(
            "home/environment/living/living",
            {"hostname": "living", "temperature": 20.0},
        ),
    )
    controller._on_message(
        None,
        None,
        _Message(
            "home/environment/ecowitt-indoor",
            {"device_name": "ecowitt-indoor", "temperature": 22.0},
        ),
    )

    assert controller.latest_inside_temperature == 21.0
    assert controller.indoor_sensor_count == 2


def test_hvac_status_includes_commanded_relay_states():
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _RecordingMqttClient()
    controller.heater_relay_on = True
    controller.fan_relay_on = True
    controller._broadcast_status_telemetry(19.0)

    topic, payload = controller.client.messages[-1]
    assert topic == "home/environment/inside"
    assert payload["heater_relay_on"] is True
    assert payload["cooler_relay_on"] is False
    assert payload["fan_relay_on"] is True


def test_hvac_turns_outputs_off_when_no_indoor_temperature_is_available():
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _MqttClient()
    controller.current_state = "HEATING"
    controller.sequence_state = "HEATING"
    controller.latest_inside_temperature = None
    commands = []
    controller._write_relays = commands.append

    controller._process_control_tick()

    assert controller.current_state == "OFF"
    assert controller.sequence_state == "OFF"
    assert commands == ["OFF"]


def test_manual_heat_waits_for_fan_lead_before_energizing_heater(monkeypatch):
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _MqttClient()
    controller.latest_inside_temperature = 21.0
    commands = []
    clock = [0.0]
    monkeypatch.setattr(hvac_daemon.time, "time", lambda: clock[0])
    controller._write_relays = commands.append

    controller._handle_manual_command("HEATING")

    assert controller.manual_target == "HEATING"
    assert controller.sequence_state == "PREHEAT"
    assert commands == ["FAN"]

    clock[0] = controller.fan_preheat_seconds
    controller._process_control_tick()

    assert controller.current_state == "HEATING"
    assert commands[-1] == "HEATING"


def test_manual_fan_toggle_never_turns_fan_off_during_heating(monkeypatch):
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _MqttClient()
    controller.latest_inside_temperature = 21.0
    controller.current_state = "HEATING"
    controller.sequence_state = "HEATING"
    controller.active_run_started_at = 0.0
    controller.manual_target = "HEATING"
    commands = []
    monkeypatch.setattr(hvac_daemon.time, "time", lambda: 0.0)
    controller._write_relays = commands.append

    controller._handle_manual_command("FAN")

    assert controller.current_state == "HEATING"
    assert controller.sequence_state == "HEATING"
    assert commands == []


def test_manual_fan_can_be_turned_on_and_off_without_heat_or_cooling(monkeypatch):
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _MqttClient()
    controller.latest_inside_temperature = None
    commands = []
    monkeypatch.setattr(hvac_daemon.time, "time", lambda: 0.0)

    def write_relays(mode):
        commands.append(mode)
        controller.fan_relay_on = mode in ("HEATING", "COOLING", "FAN")

    controller._write_relays = write_relays

    controller._handle_manual_command("FAN")
    controller._handle_manual_command("FAN")

    assert commands == ["FAN", "OFF"]
    assert controller.manual_target == "OFF"
    assert controller.sequence_state == "OFF"


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
