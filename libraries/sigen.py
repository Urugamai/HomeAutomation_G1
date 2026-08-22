from core.interface import DataSourceInterface
from typing import Dict, Any

class SigenWebClient(DataSourceInterface):
    def __init__(self, endpoint: str, credentials: dict):
        self.endpoint = endpoint
        self.credentials = credentials
    def connect(self) -> bool:
        return True
    def fetch_data(self) -> Dict[str, Any]:
        return {
            "solar_kwh_today": 12.4,
            "battery_soc": 85,
            "battery_flow": 1200,
            "grid_flow": -450
        }
    def disconnect(self) -> None:
        pass
