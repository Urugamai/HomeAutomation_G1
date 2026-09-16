"""Durable HVAC settings shared by the controller and its user interface."""

import json
import logging
import math
import os
from pathlib import Path

LOGGER = logging.getLogger(__name__)


class HvacSettingsStore:
    STORAGE_PATH = Path("/mnt/WatsonHome/hvac_settings.json")
    DEFAULTS = {
        "target_min": 20.0,
        "target_max": 24.0,
        "fan_preheat_seconds": 60.0,
        "fan_postrun_seconds": 120.0,
        "min_run_seconds": 300.0,
        "max_run_seconds": 600.0,
        "rest_seconds": 300.0,
    }

    def __init__(self, storage_path=None):
        self.storage_path = Path(storage_path or self.STORAGE_PATH)

    @classmethod
    def normalize(cls, settings):
        values = {
            key: float(settings.get(key, default))
            for key, default in cls.DEFAULTS.items()
        }
        if (
            not all(math.isfinite(value) for value in values.values())
            or values["target_min"] >= values["target_max"]
            or values["min_run_seconds"] <= 0
            or values["max_run_seconds"] < values["min_run_seconds"]
            or any(
                values[key] < 0
                for key in (
                    "fan_preheat_seconds",
                    "fan_postrun_seconds",
                    "rest_seconds",
                )
            )
        ):
            raise ValueError("HVAC settings are outside their safe ranges")
        return values

    def load(self):
        if not self.storage_path.is_file():
            return None
        try:
            with self.storage_path.open("r", encoding="utf-8") as settings_file:
                return self.normalize(json.load(settings_file))
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            LOGGER.warning(
                "Unable to load HVAC settings from %s: %s",
                self.storage_path,
                exc,
            )
            return None

    def save(self, settings):
        normalized = self.normalize(settings)
        if not self.storage_path.parent.is_dir():
            raise OSError(
                f"HVAC settings storage is unavailable: {self.storage_path.parent}"
            )
        temporary_path = self.storage_path.with_suffix(".tmp")
        try:
            with temporary_path.open("w", encoding="utf-8") as settings_file:
                json.dump(normalized, settings_file, separators=(",", ":"))
                settings_file.flush()
                os.fsync(settings_file.fileno())
            os.replace(temporary_path, self.storage_path)
        except OSError:
            try:
                temporary_path.unlink()
            except OSError:
                pass
            raise
        return normalized
