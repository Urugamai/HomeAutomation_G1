"""Compatibility helpers for Paho MQTT 1.x and 2.x."""

import paho.mqtt.client as mqtt


def create_client():
    """Create a client using the available Paho callback API."""
    callback_api = getattr(mqtt, "CallbackAPIVersion", None)
    if callback_api is not None:
        return mqtt.Client(callback_api_version=callback_api.VERSION2)
    return mqtt.Client()
