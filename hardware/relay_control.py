import time
try:
    import smbus2
except ImportError:
    class MockSMBus:
        def write_byte_data(self, addr, cmd, val): pass
    smbus2 = MockSMBus()

class HvacRelayController:
    I2C_ADDRESS = 0x20
    def __init__(self):
        self.bus = smbus2.SMBus(1) if hasattr(smbus2, 'SMBus') else smbus2.MockSMBus()
        self.off_all()

    def set_state(self, mode: str):
        if mode == "HEATING":
            byte_val = 0x05
        elif mode == "COOLING":
            byte_val = 0x06
        else:
            byte_val = 0x00
        try:
            if hasattr(self.bus, 'write_byte_data'):
                self.bus.write_byte_data(self.I2C_ADDRESS, 0, byte_val)
        except Exception as e:
            print(f"I2C Relay Write Error: {e}")

    def off_all(self):
        self.set_state("OFF")
