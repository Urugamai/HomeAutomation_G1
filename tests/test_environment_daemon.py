import json
from types import SimpleNamespace

from controllers import environment_daemon


class FakeSMBus:
    def __init__(self, bus_id):
        self.bus_id = bus_id
        self.writes = []

    def read_byte_data(self, address, register):
        raise OSError("No Bosch sensor attached")

    def read_byte(self, address):
        assert address == environment_daemon.LivingAreaHardwareController.ADDR_VEML6030
        return 0

    def write_word_data(self, address, register, value):
        self.writes.append((address, register, value))

    def read_word_data(self, address, register):
        assert address == environment_daemon.LivingAreaHardwareController.ADDR_VEML6030
        assert register == 0x04
        return 500


class NoSensorSMBus:
    def __init__(self, bus_id):
        self.bus_id = bus_id

    def read_byte_data(self, address, register):
        raise OSError("No Bosch sensor attached")

    def read_byte(self, address):
        raise OSError("No VEML sensor attached")


class RecordingMqttClient:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, retain):
        self.messages.append((topic, json.loads(payload), retain))


def test_veml_initializes_and_reports_measurement_without_gpio(monkeypatch):
    bus = FakeSMBus(1)
    monkeypatch.setattr(environment_daemon, "IS_RASPI", True)
    monkeypatch.setattr(
        environment_daemon,
        "smbus2",
        SimpleNamespace(SMBus=lambda bus_id: bus),
    )

    controller = environment_daemon.LivingAreaHardwareController()

    assert controller.bus is bus
    assert controller.veml_is_online is True
    assert bus.writes == [(0x10, 0x00, 0x0000)]

    _, _, lux, _ = controller._read_sensors()

    assert lux == 28.8


def test_real_host_without_i2c_sensors_reports_null_readings(monkeypatch):
    monkeypatch.setattr(environment_daemon, "IS_RASPI", True)
    monkeypatch.setattr(
        environment_daemon,
        "smbus2",
        SimpleNamespace(SMBus=NoSensorSMBus),
    )

    controller = environment_daemon.LivingAreaHardwareController()

    assert controller._read_sensors() == (None, None, None, None)


def test_non_simulated_host_without_i2c_bus_reports_null_readings(monkeypatch):
    controller = object.__new__(environment_daemon.LivingAreaHardwareController)
    controller.bus = None
    monkeypatch.setattr(environment_daemon, "IS_RASPI", False)
    monkeypatch.setattr(environment_daemon, "IS_SIMULATION", False)

    assert controller._read_sensors() == (None, None, None, None)


def test_telemetry_serializes_missing_sensor_readings_as_null():
    controller = object.__new__(environment_daemon.LivingAreaHardwareController)
    controller.hostname = "sensorless-host"
    controller.mqtt_client = RecordingMqttClient()

    controller._publish_telemetry(None, None, None, None)

    topic, payload, retained = controller.mqtt_client.messages[0]
    assert topic == "home/environment/living/sensorless-host"
    assert retained is True
    assert payload["temperature"] is None
    assert payload["humidity"] is None
    assert payload["pressure"] is None
    assert payload["light_lux"] is None
    assert len(controller.mqtt_client.messages) == 1
