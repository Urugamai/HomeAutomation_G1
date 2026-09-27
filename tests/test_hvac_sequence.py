import datetime
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
        self.subscriptions = []

    def publish(self, topic, payload):
        self.messages.append((topic, json.loads(payload)))

    def subscribe(self, topic):
        self.subscriptions.append(topic)


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


class _FailingGpio:
    HIGH = 1

    def setmode(self, mode):
        raise RuntimeError("Cannot determine SOC peripheral base address")


class _FakeLgpio:
    def __init__(self):
        self.claims = []
        self.writes = []

    def gpiochip_open(self, chip):
        assert chip == 0
        return 1

    def gpio_claim_output(self, chip, pin, value):
        self.claims.append((chip, pin, value))

    def gpio_write(self, chip, pin, value):
        self.writes.append((chip, pin, value))

    def gpiochip_close(self, chip):
        raise AssertionError(f"Unexpected close for GPIO chip {chip}")


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


def test_waveshare_relay_mapping_falls_back_to_lgpio(monkeypatch):
    lgpio = _FakeLgpio()
    monkeypatch.setattr(hvac_daemon, "GPIO", _FailingGpio())
    monkeypatch.setattr(hvac_daemon, "lgpio", lgpio)
    monkeypatch.setattr(hvac_daemon, "IS_RASPI", True)

    controller = hvac_daemon.HvacHardwareDaemon()
    controller._write_relays("COOLING")

    assert controller._gpio_backend == "lgpio"
    assert lgpio.claims == [
        (1, controller.RELAY_HEAT, 1),
        (1, controller.RELAY_COOL, 1),
        (1, controller.RELAY_FAN, 1),
    ]
    assert lgpio.writes[-4:] == [
        (1, controller.RELAY_HEAT, 1),
        (1, controller.RELAY_COOL, 1),
        (1, controller.RELAY_FAN, 0),
        (1, controller.RELAY_COOL, 0),
    ]


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


def test_heating_does_not_request_blind_closure_for_solar_gain():
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _RecordingMqttClient()
    controller.latest_inside_temperature = controller.t_min - 1.0
    controller._write_relays = lambda mode: None

    controller._process_control_tick()

    assert all(topic != "home/blinds/command" for topic, _ in controller.client.messages)


def test_cooling_requests_blind_closure():
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _RecordingMqttClient()
    controller.latest_inside_temperature = controller.t_max + 1.0
    controller._write_relays = lambda mode: None

    controller._process_control_tick()

    assert ("home/blinds/command", {"action": "CLOSE", "reason": "HVAC_PRECOOL"}) in (
        controller.client.messages
    )


def test_hvac_continues_heat_and_cooling_half_degree_beyond_setpoints():
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.environment_sources["Ecowitt"] = {"temperature": 20.0}

    controller.current_state = "HEATING"
    assert controller._requested_state(controller.t_min + 0.49) == "HEATING"
    assert controller._requested_state(controller.t_min + 0.5) == "OFF"

    controller.current_state = "COOLING"
    controller.environment_sources["Ecowitt"] = {"temperature": 24.0}
    assert controller._requested_state(controller.t_max - 0.49) == "COOLING"
    assert controller._requested_state(controller.t_max - 0.5) == "OFF"


def test_hvac_outdoor_midpoint_gate_blocks_inefficient_modes():
    controller = hvac_daemon.HvacHardwareDaemon()
    midpoint = (controller.t_min + controller.t_max) / 2

    controller.environment_sources["Ecowitt"] = {"temperature": midpoint + 0.1}
    assert controller._requested_state(controller.t_min - 1.0) == "OFF"

    controller.environment_sources["Ecowitt"] = {"temperature": midpoint - 0.1}
    assert controller._requested_state(controller.t_max + 1.0) == "OFF"


def test_vacation_stops_normal_control_and_runs_weekly_exercise(tmp_path):
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _MqttClient()
    controller.settings_store = HvacSettingsStore(tmp_path / "hvac-settings.json")
    start = datetime.date(2030, 1, 1)
    end = datetime.date(2030, 1, 3)
    now = datetime.datetime.combine(start, datetime.time(hour=18)).timestamp()
    commands = []
    controller._write_relays = commands.append
    controller.vacation_start = start
    controller.vacation_end = end
    controller.current_state = "HEATING"
    controller.sequence_state = "HEATING"
    controller.active_run_started_at = now - 60
    controller.fan_preheat_seconds = 0
    controller.fan_postrun_seconds = 120

    assert controller._process_vacation_control(now, 20.0) is True
    assert controller.sequence_state == "POSTRUN"
    assert commands[-1] == "FAN"

    controller.sequence_state = "OFF"
    controller.fan_postrun_seconds = 0
    assert controller._process_vacation_control(now + 5, 20.0) is True
    assert controller.current_state == "HEATING"
    assert controller.vacation_last_exercise_date == start
    assert commands[-1] == "HEATING"

    controller._process_vacation_control(
        now + 5 + hvac_daemon.VACATION_EXERCISE_SECONDS,
        20.0,
    )
    assert controller.sequence_state == "OFF"
    assert commands[-1] == "OFF"

    return_date = datetime.datetime.combine(end, datetime.time(hour=9)).timestamp()
    assert controller._process_vacation_control(return_date, 20.0) is False


def test_vacation_activates_at_1800_and_resumes_at_0900():
    controller = hvac_daemon.HvacHardwareDaemon()
    start = datetime.date(2030, 1, 1)
    end = start + datetime.timedelta(days=2)
    controller.vacation_start = start
    controller.vacation_end = end

    assert controller._is_vacation_active(
        datetime.datetime.combine(start, datetime.time(hour=17, minute=59))
    ) is False
    assert controller._is_vacation_active(
        datetime.datetime.combine(start, datetime.time(hour=18))
    ) is True
    assert controller._is_vacation_active(
        datetime.datetime.combine(end, datetime.time(hour=8, minute=59))
    ) is True
    assert controller._is_vacation_active(
        datetime.datetime.combine(end, datetime.time(hour=9))
    ) is False


def test_vacation_uses_configured_start_and_resume_times():
    controller = hvac_daemon.HvacHardwareDaemon()
    start = datetime.date(2030, 1, 1)
    end = start + datetime.timedelta(days=2)
    controller.vacation_start = start
    controller.vacation_end = end
    controller.vacation_start_time = datetime.time(hour=16, minute=30)
    controller.vacation_end_time = datetime.time(hour=10, minute=15)

    assert controller._is_vacation_active(
        datetime.datetime.combine(start, datetime.time(hour=16, minute=29))
    ) is False
    assert controller._is_vacation_active(
        datetime.datetime.combine(start, datetime.time(hour=16, minute=30))
    ) is True
    assert controller._is_vacation_active(
        datetime.datetime.combine(end, datetime.time(hour=10, minute=14))
    ) is True
    assert controller._is_vacation_active(
        datetime.datetime.combine(end, datetime.time(hour=10, minute=15))
    ) is False


def test_vacation_clears_manual_hvac_override():
    controller = hvac_daemon.HvacHardwareDaemon()
    start = datetime.date(2030, 1, 1)
    now = datetime.datetime.combine(start, datetime.time(hour=18)).timestamp()
    commands = []
    controller._write_relays = commands.append
    controller.vacation_start = start
    controller.vacation_end = start + datetime.timedelta(days=2)
    controller.manual_target = "HEATING"
    controller.current_state = "HEATING"
    controller.sequence_state = "MANUAL_HEATING"
    controller.fan_postrun_seconds = 0

    assert controller._process_vacation_control(now, 20.0) is True
    assert controller.manual_target is None
    assert controller.sequence_state == "OFF"
    assert commands == ["OFF"]


def test_manual_heat_uses_preheat_and_postrun_delays(monkeypatch):
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _MqttClient()
    clock = [0.0]
    monkeypatch.setattr(hvac_daemon.time, "time", lambda: clock[0])
    commands = []

    def write_relays(mode):
        commands.append(mode)
        controller.heater_relay_on = mode == "HEATING"
        controller.cooler_relay_on = mode == "COOLING"
        controller.fan_relay_on = mode in ("HEATING", "COOLING", "FAN")

    controller._write_relays = write_relays

    controller._handle_manual_command("HEATING")

    assert controller.manual_target == "HEATING"
    assert controller.current_state == "OFF"
    assert controller.sequence_state == "MANUAL_PREHEAT"
    assert commands == ["FAN"]

    clock[0] = controller.fan_preheat_seconds
    controller._process_control_tick()

    assert controller.current_state == "HEATING"
    assert controller.sequence_state == "MANUAL_HEATING"
    assert commands == ["FAN", "HEATING"]

    controller._handle_manual_command("HEATING")

    assert controller.manual_target == "OFF"
    assert controller.current_state == "OFF"
    assert controller.sequence_state == "MANUAL_POSTRUN"
    assert commands[-1] == "FAN"

    clock[0] += controller.fan_postrun_seconds
    controller._process_control_tick()

    assert controller.manual_target == "OFF"
    assert controller.sequence_state == "MANUAL_OFF"
    assert commands[-1] == "OFF"


def test_manual_cooling_uses_preheat_without_temperature_telemetry(monkeypatch):
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _MqttClient()
    clock = [0.0]
    monkeypatch.setattr(hvac_daemon.time, "time", lambda: clock[0])
    commands = []

    def write_relays(mode):
        commands.append(mode)
        controller.heater_relay_on = mode == "HEATING"
        controller.cooler_relay_on = mode == "COOLING"
        controller.fan_relay_on = mode in ("HEATING", "COOLING", "FAN")

    controller._write_relays = write_relays

    controller._handle_manual_command("COOLING")

    assert controller.sequence_state == "MANUAL_PREHEAT"
    assert commands == ["FAN"]

    clock[0] = controller.fan_preheat_seconds
    controller._process_control_tick()

    assert controller.current_state == "COOLING"
    assert controller.sequence_state == "MANUAL_COOLING"
    assert commands == ["FAN", "COOLING"]


def test_manual_preheat_status_includes_target_and_deadline(monkeypatch):
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _RecordingMqttClient()
    monkeypatch.setattr(hvac_daemon.time, "time", lambda: 100.0)
    controller._write_relays = lambda mode: None

    controller._handle_manual_command("COOLING")

    _, payload = controller.client.messages[-1]
    assert payload["hvac_sequence_state"] == "MANUAL_PREHEAT"
    assert payload["hvac_pending_state"] == "COOLING"
    assert payload["hvac_transition_ends_at"] == 160.0


def test_manual_heating_restarts_preheat_when_requested_during_postrun():
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _MqttClient()
    commands = []

    def write_relays(mode):
        commands.append(mode)
        controller.heater_relay_on = mode == "HEATING"
        controller.cooler_relay_on = mode == "COOLING"
        controller.fan_relay_on = mode in ("HEATING", "COOLING", "FAN")

    controller._write_relays = write_relays

    controller._handle_manual_command("HEATING")
    controller._handle_manual_command("FAN")
    controller._handle_manual_command("HEATING")

    assert controller.manual_target == "HEATING"
    assert controller.manual_fan_requested is False
    assert controller.sequence_state == "MANUAL_PREHEAT"
    assert commands == ["FAN", "FAN", "FAN"]


def test_manual_fan_command_cancels_manual_heating_with_postrun(monkeypatch):
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _MqttClient()
    controller.latest_inside_temperature = 21.0
    controller.current_state = "HEATING"
    controller.sequence_state = "MANUAL_HEATING"
    controller.active_run_started_at = 0.0
    controller.manual_target = "HEATING"
    controller.heater_relay_on = True
    controller.fan_relay_on = True
    commands = []
    monkeypatch.setattr(hvac_daemon.time, "time", lambda: 0.0)
    controller._write_relays = commands.append

    controller._handle_manual_command("FAN")

    assert controller.current_state == "OFF"
    assert controller.sequence_state == "MANUAL_POSTRUN"
    assert controller.manual_target == "OFF"
    assert controller.manual_fan_requested is False
    assert commands == ["FAN"]


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
    assert controller.manual_target is None
    assert controller.sequence_state == "OFF"


def test_returning_hvac_to_auto_clears_blind_automation_holds():
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _RecordingMqttClient()
    controller.manual_target = "HEATING"
    controller.sequence_state = "MANUAL_HEATING"
    controller._write_relays = lambda mode: None

    controller._handle_manual_command("AUTO")

    topic, payload = next(
        message
        for message in controller.client.messages
        if message[0] == "home/blinds/command"
    )
    assert payload == {
        "action": "RESET_AUTOMATION_HOLDS",
        "reason": "HVAC_AUTO",
    }


def test_hvac_connection_releases_stale_blind_locks():
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _RecordingMqttClient()

    controller._on_connect(controller.client, None, None, 0)

    assert ("home/blinds/command", {"action": "RELEASE_HVAC_LOCKS"}) in (
        controller.client.messages
    )


def test_hvac_postrun_releases_blind_locks(monkeypatch):
    controller = hvac_daemon.HvacHardwareDaemon()
    controller.client = _RecordingMqttClient()
    controller.latest_inside_temperature = 22.0
    controller.sequence_state = "POSTRUN"
    controller.sequence_started_at = 0.0
    controller.fan_postrun_seconds = 120.0
    controller.blind_pre_close_triggered = True
    monkeypatch.setattr(hvac_daemon.time, "time", lambda: 120.0)
    controller._write_relays = lambda mode: None

    controller._process_control_tick()

    assert ("home/blinds/command", {"action": "RELEASE_HVAC_LOCKS"}) in (
        controller.client.messages
    )
    assert controller.blind_pre_close_triggered is False


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


def test_hvac_settings_validate_vacation_window(tmp_path):
    store = HvacSettingsStore(tmp_path / "hvac_settings.json")
    settings = store.save(
        {
            "vacation_start": "2030-01-01",
            "vacation_end": "2030-01-08",
        }
    )

    assert settings["vacation_start"] == "2030-01-01"
    assert settings["vacation_end"] == "2030-01-08"
    assert settings["vacation_start_time"] == "18:00"
    assert settings["vacation_end_time"] == "09:00"

    with pytest.raises(ValueError):
        store.normalize(
            {
                "vacation_start": "2030-01-08",
                "vacation_end": "2030-01-01",
            }
        )


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
