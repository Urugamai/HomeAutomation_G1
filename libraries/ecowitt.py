from core.interface import DataSourceInterface
from typing import Dict, Any

class EcowittClient(DataSourceInterface):
    def connect(self) -> bool:
        return True
    def fetch_data(self) -> Dict[str, Any]:
        return {
            "outside_temp": 14.5,
            "outside_humidity": 82,
            "outside_pressure": 1013.2,
            "outside_light": 4500,
            "rain_today": 2.4,
            "wind_speed": 12.5
        }
    def disconnect(self) -> None:
        pass
