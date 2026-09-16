import pytest

import controllers.environment_daemon as environment_daemon
import controllers.hvac_daemon as hvac_daemon


class _MqttClient:
    def publish(self, *args, **kwargs):
        pass


@pytest.mark.parametrize(
    ("module", "controller_class", "tick_method", "state_attr", "sequence_attr"),
    [
        (
            hvac_daemon,
            hvac_daemon.HvacHardwareDaemon,
            "_process_control_tick",
            "current_state",
            "sequence_state",
        ),
        (
            environment_daemon,
            environment_daemon.LivingAreaHardwareController,
            "_process_automation_tick",
            "current_hvac_state",
            "hvac_sequence_state",
        ),
    ],
)
def test_hvac_fan_lead_minimum_run_and_postrun(
    monkeypatch, module, controller_class, tick_method, state_attr, sequence_attr
):
    controller = controller_class()
    commands = []
    temperatures = [19.0]
    clock = [0.0]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])

    if controller_class is hvac_daemon.HvacHardwareDaemon:
        controller.client = _MqttClient()
        controller._read_inside_temperature = lambda: temperatures[0]
        controller._write_relays = commands.append
    else:
        controller.mqtt_client = _MqttClient()
        controller._read_sensors = lambda: (temperatures[0], 50.0, 0.0, 1013.0)
        controller._apply_physical_relay_state = commands.append

    getattr(controller, tick_method)()
    assert getattr(controller, sequence_attr) == "PREHEAT"
    assert commands[-1] == "FAN"

    clock[0] = 60.0
    getattr(controller, tick_method)()
    assert getattr(controller, state_attr) == "HEATING"
    assert commands[-1] == "HEATING"

    temperatures[0] = 22.0
    clock[0] = 359.0
    getattr(controller, tick_method)()
    assert getattr(controller, state_attr) == "HEATING"

    clock[0] = 360.0
    getattr(controller, tick_method)()
    assert getattr(controller, sequence_attr) == "POSTRUN"
    assert commands[-1] == "FAN"

    clock[0] = 480.0
    getattr(controller, tick_method)()
    assert getattr(controller, sequence_attr) == "OFF"
    assert commands[-1] == "OFF"


@pytest.mark.parametrize(
    ("module", "controller_class", "tick_method", "sequence_attr"),
    [
        (
            hvac_daemon,
            hvac_daemon.HvacHardwareDaemon,
            "_process_control_tick",
            "sequence_state",
        ),
        (
            environment_daemon,
            environment_daemon.LivingAreaHardwareController,
            "_process_automation_tick",
            "hvac_sequence_state",
        ),
    ],
)
def test_hvac_maximum_run_starts_rest_period(
    monkeypatch, module, controller_class, tick_method, sequence_attr
):
    controller = controller_class()
    commands = []
    clock = [0.0]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])

    if controller_class is hvac_daemon.HvacHardwareDaemon:
        controller.client = _MqttClient()
        controller._read_inside_temperature = lambda: 19.0
        controller._write_relays = commands.append
    else:
        controller.mqtt_client = _MqttClient()
        controller._read_sensors = lambda: (19.0, 50.0, 0.0, 1013.0)
        controller._apply_physical_relay_state = commands.append

    controller.fan_preheat_seconds = 0
    controller.fan_postrun_seconds = 0
    getattr(controller, tick_method)()
    assert getattr(controller, sequence_attr) == "HEATING"

    clock[0] = 600.0
    getattr(controller, tick_method)()
    assert getattr(controller, "is_resting", False) or getattr(
        controller, "in_rest_period", False
    )
    assert commands[-1] == "OFF"
