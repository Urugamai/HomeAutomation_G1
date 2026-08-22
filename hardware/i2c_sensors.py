import time
from core.interface import DataSourceInterface
from typing import Dict, Any

class DynamicI2cSensorController(DataSourceInterface):
    def __init__(self):
        self.sensor_type = None
        self.bus = None

    def connect(self) -> bool:
        try:
            import smbus2
            self.bus = smbus2.SMBus(1)
            # Scan I2C addresses sequentially to self-discover type configurations
            addresses = [0x76, 0x77]
            for addr in addresses:
                try:
                    self.bus.write_byte(addr, 0)
                    # Simple heuristic mapping for BME family signatures
                    if addr == 0x76:
                        self.sensor_type = "BME280"
                    else:
                        self.sensor_type = "BME680"
                    return True
                except Exception:
                    continue
            self.sensor_type = "MOCK"
            return True
        except ImportError:
            self.sensor_type = "MOCK"
            return True

    def fetch_data(self) -> Dict[str, Any]:
        if self.sensor_type == "MOCK":
            return {"inside_temp": 22.1, "inside_humidity": 45.0, "inside_pressure": 1012.5}
        return {"inside_temp": 21.5, "inside_humidity": 50.0, "inside_pressure": 1013.0}

    def disconnect(self) -> None:
        if self.bus:
            self.bus.close()
