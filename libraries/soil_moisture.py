"""Soil moisture sensor helpers shared by the controller pages."""

import re

GREEN = "#28a745"
AMBER = "#ffc107"
RED = "#dc3545"

MOISTURE_AMBER_LOW = 30.0
MOISTURE_AMBER_HIGH = 70.0
MOISTURE_RED_LOW = 15.0
MOISTURE_RED_HIGH = 90.0

# WH51 sensors run on one AA cell; Ecowitt flags them as low at about 1.2 V.
BATTERY_RED_VOLTS = 1.2
BATTERY_EMPTY_VOLTS = 1.0
BATTERY_FULL_VOLTS = 1.6
# Gateways that report a percentage instead of volts are red at 20% or less.
BATTERY_RED_PERCENT = 20.0

_CHANNEL_KEY = re.compile(r"^soil_(moisture|battery)_ch(\d+)$")


def moisture_color(percent):
    if percent < MOISTURE_RED_LOW or percent > MOISTURE_RED_HIGH:
        return RED
    if percent < MOISTURE_AMBER_LOW or percent > MOISTURE_AMBER_HIGH:
        return AMBER
    return GREEN


def _battery_is_percent(value):
    return value > 6.0


def battery_fraction(value):
    if _battery_is_percent(value):
        return max(0.0, min(1.0, value / 100.0))
    span = BATTERY_FULL_VOLTS - BATTERY_EMPTY_VOLTS
    return max(0.0, min(1.0, (value - BATTERY_EMPTY_VOLTS) / span))


def battery_color(value):
    if _battery_is_percent(value):
        return RED if value <= BATTERY_RED_PERCENT else GREEN
    return RED if value <= BATTERY_RED_VOLTS else GREEN


def battery_text(value):
    return f"{value:.0f}%" if _battery_is_percent(value) else f"{value:.2f} V"


def soil_sensors(source):
    """Return [(channel, moisture_or_None, battery_or_None)] sorted by channel."""
    readings = {}
    for key, value in (source or {}).items():
        match = _CHANNEL_KEY.match(str(key))
        if not match:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        entry = readings.setdefault(int(match.group(2)), [None, None])
        entry[0 if match.group(1) == "moisture" else 1] = number
    return [(channel, m, b) for channel, (m, b) in sorted(readings.items())]
