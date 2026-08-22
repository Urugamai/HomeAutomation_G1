from core.interface import DataSourceInterface
from typing import Dict, Any

class OcularModbusController(DataSourceInterface):
    def __init__(self, ip_address: str = "192.168.1.50", port: int = 502):
        self.ip_address = ip_address
        self.port = port
    def connect(self) -> bool:
        return True
    def fetch_data(self) -> Dict[str, Any]:
        return {"status_code": 1, "current_amps": 16, "energy_delivered_kwh": 4.2}
    def send_charge_command(self, charge_rate_amps: int):
        pass
    def disconnect(self) -> None:
        pass
