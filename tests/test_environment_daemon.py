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


class DisabledI2CBus:
    def __init__(self, bus_id):
        raise FileNotFoundError(2, "No such file or directory", "/dev/i2c-1")


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


def test_disabled_i2c_logs_raspi_config_remediation(monkeypatch, capsys):
    monkeypatch.setattr(environment_daemon, "IS_RASPI", True)
    monkeypatch.setattr(
        environment_daemon,
        "smbus2",
        SimpleNamespace(SMBus=DisabledI2CBus),
    )

    environment_daemon.LivingAreaHardwareController()

    assert "[I2C DISABLED]" in capsys.readouterr().out


def test_non_simulated_host_without_i2c_bus_reports_null_readings(monkeypatch):
    controller = object.__new__(environment_daemon.LivingAreaHardwareController)
    controller.bus = None
    monkeypatch.setattr(environment_daemon, "IS_RASPI", False)
    monkeypatch.setattr(environment_daemon, "IS_SIMULATION", False)

    assert controller._read_sensors() == (None, None, None, None)


def test_missing_hardware_is_reprobed_after_the_retry_interval(monkeypatch):
    controller = object.__new__(environment_daemon.LivingAreaHardwareController)
    controller.hostname = "lounge-clock"
    controller.discovered_bme_addr = None
    controller.veml_is_online = False
    controller._next_hardware_retry_at = 0.0
    controller.HARDWARE_RETRY_SECONDS = 60
    probes = []
    controller._initialize_hardware = lambda: probes.append("probe")
    monkeypatch.setattr(environment_daemon, "IS_RASPI", True)
    monkeypatch.setattr(environment_daemon.time, "monotonic", lambda: 100.0)

    controller._retry_missing_hardware()
    controller._retry_missing_hardware()

    assert probes == ["probe"]
    assert controller._next_hardware_retry_at == 160.0


def test_telemetry_serializes_missing_sensor_readings_as_null():
    controller = object.__new__(environment_daemon.LivingAreaHardwareController)
    controller.hostname = "sensorless-host"
    controller.mqtt_client = RecordingMqttClient()

    controller._publish_telemetry(None, None, None, None)

    shared_topic, shared_payload, retained = controller.mqtt_client.messages[0]
    assert shared_topic == "home/environment/living"
    assert retained is True
    assert shared_payload["temperature"] is None
    assert shared_payload["humidity"] is None
    assert shared_payload["pressure"] is None
    assert shared_payload["light_w_m2"] is None

    topic, payload, retained = controller.mqtt_client.messages[1]
    assert topic == "home/environment/living/sensorless-host"
    assert retained is True
    assert payload == shared_payload

    controller._publish_telemetry(None, None, None, None)

    assert len(controller.mqtt_client.messages) == 3
