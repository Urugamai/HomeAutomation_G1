from abc import ABC, abstractmethod
from typing import Any, Dict

class DataSourceInterface(ABC):
    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def fetch_data(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass
