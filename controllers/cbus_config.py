import configparser
from pathlib import Path


class CBusConfigManager:
    """Manages reading structural environments and fallbacks from config.ini."""

    def __init__(self):
        self.config_path = Path(__file__).resolve().parent.parent / "config.ini"

    def get_cbus_settings(self) -> dict:
        """Extracts C-Bus interface network profiles."""
        settings = {"host": "192.168.2.2", "port": 2000, "timeout": 1.0, "xml_path": ""}
        if self.config_path.exists():
            try:
                config = configparser.ConfigParser()
                config.read(str(self.config_path))
                if config.has_section("CBUS"):
                    settings["host"] = config.get("CBUS", "host", fallback="192.168.2.2")
                    settings["port"] = config.getint("CBUS", "port", fallback=2000)
                    settings["timeout"] = config.getfloat("CBUS", "timeout", fallback=1.0)
                    settings["xml_path"] = config.get("CBUS", "xml_path", fallback="")
            except Exception as e:
                print(f"[CONFIG ERROR] Failed loading CBUS environment: {e}")
        return settings

    def get_mqtt_broker(self) -> str:
        """Extracts target network MQTT loop endpoints."""
        if self.config_path.exists():
            try:
                config = configparser.ConfigParser()
                config.read(str(self.config_path))
                return config.get("MQTT", "broker", fallback="localhost")
            except Exception:
                pass
        return "localhost"
