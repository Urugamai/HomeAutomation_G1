import json

from libraries.mqtt_engine import MqttTelemetryListener


def test_hvac_status_updates_individual_relay_states():
    listener = MqttTelemetryListener()

    listener._update_hvac_status(
        {
            "hvac_state": "COOLING",
            "hvac_in_rest": False,
            "hvac_sequence_state": "COOLING",
            "hvac_pending_state": None,
            "hvac_transition_ends_at": None,
            "heater_relay_on": False,
            "cooler_relay_on": True,
            "fan_relay_on": True,
        }
    )

    assert listener.cached_data["hvac_state"] == "COOLING"
    assert listener.cached_data["heater_relay_on"] is False
    assert listener.cached_data["cooler_relay_on"] is True
    assert listener.cached_data["fan_relay_on"] is True
    assert listener.cached_data["hvac_pending_state"] is None
    assert listener.cached_data["hvac_transition_ends_at"] is None


def test_hvac_status_retains_transition_target_and_deadline():
    listener = MqttTelemetryListener()

    listener._update_hvac_status(
        {
            "hvac_sequence_state": "MANUAL_PREHEAT",
            "hvac_pending_state": "COOLING",
            "hvac_transition_ends_at": 1234.5,
        }
    )

    assert listener.cached_data["hvac_pending_state"] == "COOLING"
    assert listener.cached_data["hvac_transition_ends_at"] == 1234.5


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


def test_charger_status_is_cached_for_controller_pages():
    listener = MqttTelemetryListener()
    message = type(
        "Message",
        (),
        {
            "topic": "home/charger/status",
            "payload": json.dumps(
                {
                    "state": "Charging",
                    "target_amps": 12,
                    "grid_flow_watts": -2800,
                    "battery_soc": 76,
                }
            ).encode(),
        },
    )()

    listener._on_message(None, None, message)

    assert listener.cached_data["charger_status"]["target_amps"] == 12
    assert listener.cached_data["charger_status"]["grid_flow_watts"] == -2800
