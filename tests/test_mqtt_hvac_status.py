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


def test_hvac_status_retains_the_daemon_indoor_average_temperature():
    listener = MqttTelemetryListener()

    listener._update_hvac_status({"temperature": 21.75})

    assert listener.cached_data["hvac_temperature"] == 21.75


def test_local_environment_telemetry_preserves_hvac_sequence_status():
    listener = MqttTelemetryListener(location="living")
    listener._update_hvac_status(
        {
            "hvac_state": "OFF",
            "hvac_in_rest": False,
            "hvac_sequence_state": "PREHEAT",
        }
    )

    listener._update_local_environment(
        {
            "hostname": "living",
            "temperature": 20.0,
            "humidity": 50.0,
            "light_lux": 100.0,
        }
    )

    assert listener.cached_data["hvac_state"] == "OFF"
    assert listener.cached_data["hvac_sequence_state"] == "PREHEAT"
