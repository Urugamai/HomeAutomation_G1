"""Shared environment-source calculations used by the UI and HVAC daemon."""

OUTDOOR_ECOWITT_SOURCE = "Ecowitt"
TEMPERATURE_KEYS = ("temperature", "outside_temp", "outdoor_temp", "room_temp")


def temperature_value(source):
    """Return a source temperature as a float, or None when it is unavailable."""
    for key in TEMPERATURE_KEYS:
        value = source.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def indoor_temperature_average(sources):
    """Average valid indoor sources while excluding the Ecowitt outdoor source."""
    temperatures = [
        temperature
        for source_key, source in sources.items()
        if source_key != OUTDOOR_ECOWITT_SOURCE
        and (temperature := temperature_value(source)) is not None
    ]
    if not temperatures:
        return None, 0
    return sum(temperatures) / len(temperatures), len(temperatures)
