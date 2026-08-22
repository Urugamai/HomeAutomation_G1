import sys
import random
from abc import ABC, abstractmethod

# Safe, conditional hardware imports that won't crash Windows
try:
    if sys.platform != "win32":
        import smbus2
    else:
        smbus2 = None
except ImportError:
    smbus2 = None

class DataSourceInterface(ABC):
    @abstractmethod
    def connect(self) -> bool: pass
    @abstractmethod
    def fetch_data(self) -> dict: pass

class CrossPlatformSensorController(DataSourceInterface):
    """Dynamically switches between raw physical I2C data and simulation."""
    def __init__(self):
        self.is_windows = (sys.platform == "win32")
        self.bus = None

    def connect(self) -> bool:
        if self.is_windows:
            print("[INFO] Windows 11 detected. Initializing virtual environment.")
            return True
        else:
            try:
                # Attempt physical Pi I2C initialization
                if smbus2:
                    self.bus = smbus2.SMBus(1)
                    print("[INFO] Raspberry Pi I2C bus connected successfully.")
                    return True
            except Exception as e:
                print(f"[WARN] Pi Hardware failed, falling back to simulation: {e}")
                self.is_windows = True
            return True

    def fetch_data(self) -> dict:
        if self.is_windows:
            # High-fidelity dummy values for local PC design testing
            return {
                "inside_temp": round(random.uniform(21.0, 23.5), 1),
                "outside_temp": round(random.uniform(13.0, 16.5), 1),
                "battery_soc": random.randint(70, 85),
                "battery_flow": random.randint(-2000, 3000),
                "grid_flow": random.randint(-1500, 4000)
            }
        else:
            # Basic fallback if physical I2C logic is requested on the Pi
            # (Replace with your specific register extraction functions)
            return {
                "inside_temp": 22.0, "outside_temp": 15.0,
                "battery_soc": 80, "battery_flow": 500, "grid_flow": -200
            }
