from libraries.mqtt_engine import MqttTelemetryListener


def test_hvac_status_updates_individual_relay_states():
    listener = MqttTelemetryListener()

    listener._update_hvac_status(
        {
            "hvac_state": "COOLING",
            "hvac_in_rest": False,
            "hvac_sequence_state": "COOLING",
            "heater_relay_on": False,
            "cooler_relay_on": True,
            "fan_relay_on": True,
        }
    )

    assert listener.cached_data["hvac_state"] == "COOLING"
    assert listener.cached_data["heater_relay_on"] is False
    assert listener.cached_data["cooler_relay_on"] is True
    assert listener.cached_data["fan_relay_on"] is True
