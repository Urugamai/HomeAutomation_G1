import os

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "soil-sensors.yml",
)


def load_soil_names(path=DEFAULT_CONFIG_PATH):
    """Return {channel: location name} from the soil sensor mapping file."""
    if yaml is None or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file) or {}
    except (OSError, yaml.YAMLError):
        return {}
    channels = config.get("channels") if isinstance(config, dict) else None
    names = {}
    for key, value in (channels or {}).items():
        try:
            channel = int(key)
        except (TypeError, ValueError):
            continue
        if value is not None and str(value).strip():
            names[channel] = str(value).strip()
    return names
