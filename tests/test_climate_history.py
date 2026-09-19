import datetime

from ui.hvac_page import ClimateHistoryStore


def test_climate_history_persists_sensor_and_relay_samples(tmp_path):
    storage_path = tmp_path / "home_climate_history.json"
    timestamp = datetime.datetime.now().replace(microsecond=0)
    history = ClimateHistoryStore(storage_path)

    history.add_sample(
        timestamp,
        {"living": 21.5, "ecowitt-indoor": 22.0},
        14.2,
        20.0,
        24.0,
        False,
        True,
        True,
    )

    reloaded = ClimateHistoryStore(storage_path)

    assert reloaded.samples == [
        {
            "timestamp": timestamp,
            "indoor_temperatures": {"living": 21.5, "ecowitt-indoor": 22.0},
            "outdoor_temperature": 14.2,
            "heating_setpoint": 20.0,
            "cooling_setpoint": 24.0,
            "heater_on": False,
            "cooler_on": True,
            "fan_on": True,
        }
    ]
