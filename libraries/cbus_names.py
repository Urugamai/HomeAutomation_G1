import os
import re

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "cbus-display-names.yml",
)


def _key(name):
    return re.sub(r"[\s_]+", "_", str(name).strip()).upper()


class CbusNameMapper:
    def __init__(self, config=None):
        config = config or {}
        self.strip_prefixes = {
            str(p).upper() for p in config.get("strip_prefixes") or []
        }
        self.words = {
            str(k).upper(): str(v) for k, v in (config.get("words") or {}).items()
        }
        self.patterns = [
            (re.compile(p, re.IGNORECASE), str(r))
            for p, r in (config.get("patterns") or {}).items()
        ]
        self.floor_overrides = {
            _key(k): str(v).capitalize()
            for k, v in (config.get("floor_overrides") or {}).items()
        }
        self.name_overrides = {
            _key(k): str(v)
            for k, v in (config.get("name_overrides") or {}).items()
        }

        self.type_colors = {
            str(k).upper(): str(v)
            for k, v in (config.get("type_colors") or {}).items()
        }

    def color_for(self, name):
        parts = _key(name).split("_")
        device_type = parts[2] if len(parts) > 2 else ""
        return self.type_colors.get(device_type) or self.type_colors.get("OTHER")

    @classmethod
    def load(cls, path=DEFAULT_CONFIG_PATH):
        if yaml is None or not os.path.exists(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as config_file:
                return cls(yaml.safe_load(config_file))
        except (OSError, yaml.YAMLError):
            return cls()

    def floor_for(self, name):
        key = _key(name)
        if key in self.floor_overrides:
            return self.floor_overrides[key]
        if key.startswith(("G_", "OUT_")):
            return "Ground"
        if key.startswith("1_"):
            return "First"
        return None

    def display_name(self, name):
        key = _key(name)
        if key in self.name_overrides:
            return self.name_overrides[key]
        tokens = [t for t in key.split("_") if t]
        if tokens and tokens[0] in self.strip_prefixes:
            tokens = tokens[1:]
        out = []
        for token in tokens:
            if token in self.words:
                out.append(self.words[token])
                continue
            for pattern, replacement in self.patterns:
                if pattern.match(token):
                    out.append(pattern.sub(replacement, token))
                    break
            else:
                out.append(token)
        return " ".join(out) or "Unnamed C-Bus device"
