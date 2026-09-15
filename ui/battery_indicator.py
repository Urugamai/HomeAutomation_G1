"""Shared battery state display rules."""

CHARGING_COLOR = "#28a745"
DRAINING_COLOR = "#8b4513"
LOW_SOC_COLOR = "#dc3545"
FLOW_DEADBAND = 100.0
LOW_SOC_THRESHOLD = 10.0


def battery_soc_fill_color(soc, battery_flow, previous_color=CHARGING_COLOR):
    """Return the SOC fill color, preserving it while flow is in the deadband."""
    if float(soc) < LOW_SOC_THRESHOLD:
        return LOW_SOC_COLOR
    if float(battery_flow) < -FLOW_DEADBAND:
        return DRAINING_COLOR
    if float(battery_flow) > FLOW_DEADBAND:
        return CHARGING_COLOR
    return previous_color
