"""Shared battery state display rules."""

CHARGING_COLOR = "#28a745"
DRAINING_COLOR = "#ff8c00"
LOW_SOC_COLOR = "#dc3545"
FLOW_DEADBAND = 100.0
LOW_SOC_THRESHOLD = 10.0


def battery_flow_color(battery_flow, previous_color=CHARGING_COLOR):
    """Return the flow color, preserving it while flow is in the deadband."""
    if float(battery_flow) < -FLOW_DEADBAND:
        return DRAINING_COLOR
    if float(battery_flow) > FLOW_DEADBAND:
        return CHARGING_COLOR
    return previous_color


def battery_soc_fill_color(soc, flow_color):
    """Return the SOC color, with low SOC overriding the remembered flow color."""
    return LOW_SOC_COLOR if float(soc) < LOW_SOC_THRESHOLD else flow_color
