"""Configuration-driven entry point for the bundled cmqttd daemon."""

import configparser
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.ini"
CMQTTD_ROOT = PROJECT_ROOT / "hardware" / "cmqttd"


def _load_arguments() -> list[str]:
    config = configparser.ConfigParser()
    if not config.read(CONFIG_PATH):
        raise FileNotFoundError(f"CBus configuration not found: {CONFIG_PATH}")

    if not config.has_section("MQTT"):
        raise ValueError("config.ini is missing the [MQTT] section")
    if not config.has_section("CBUS"):
        raise ValueError("config.ini is missing the [CBUS] section")

    broker = config.get("MQTT", "broker")
    broker_port = config.getint("MQTT", "port", fallback=1883)
    broker_tls = config.getboolean("MQTT", "tls", fallback=False)
    cbus_host = config.get("CBUS", "host")
    cbus_port = config.getint("CBUS", "port")
    timesync = config.getint("CBUS", "timesync", fallback=300)

    arguments = [
        "--broker-address", broker,
        "--broker-port", str(broker_port),
        "--tcp", f"{cbus_host}:{cbus_port}",
        "--timesync", str(timesync),
    ]

    if not broker_tls:
        arguments.append("--broker-disable-tls")

    project_file = config.get("CBUS", "project_file", fallback="").strip()
    if project_file:
        project_path = Path(project_file).expanduser()
        if not project_path.is_absolute():
            project_path = PROJECT_ROOT / project_path
        if not project_path.is_file():
            raise FileNotFoundError(
                f"Configured cmqttd project file not found: {project_path}")
        arguments.extend(["--project-file", str(project_path)])

    return arguments


def main() -> None:
    """Run the bundled cmqttd CLI using this project's configuration."""
    if not CMQTTD_ROOT.is_dir():
        raise FileNotFoundError(f"cmqttd submodule not found: {CMQTTD_ROOT}")

    sys.path.insert(0, str(CMQTTD_ROOT))
    from cbus.daemon.cmqttd import main as cmqttd_main

    sys.argv = [str(CMQTTD_ROOT / "cmqttd")] + _load_arguments() + sys.argv[1:]
    cmqttd_main()


if __name__ == "__main__":
    main()
