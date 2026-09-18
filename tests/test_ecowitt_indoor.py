from controllers.ecowitt_daemon import EcowittLanIngestionDaemon


def test_api_payload_includes_distinct_ecowitt_indoor_measurements():
    outdoor, indoor = EcowittLanIngestionDaemon._normalise_api_payload(
        {
            "outdoor": {
                "temperature": {"value": 20.0, "unit": "C"},
                "humidity": {"value": 60},
            },
            "indoor": {
                "temperature": {"value": 68.0, "unit": "F"},
                "humidity": {"value": 45},
                "barom": {"value": 1012.4},
            },
        }
    )

    assert outdoor["temperature"] == 20.0
    assert indoor["device_name"] == "ecowitt-indoor"
    assert indoor["temperature"] == 20.0
    assert indoor["humidity"] == 45.0
    assert indoor["pressure"] == 1012.4
