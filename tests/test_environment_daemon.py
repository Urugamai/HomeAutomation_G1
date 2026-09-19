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
