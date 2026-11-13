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


def test_api_payload_includes_soil_moisture_channels():
    outdoor, _ = EcowittLanIngestionDaemon._normalise_api_payload({
        'soil_ch1': {'soilmoisture': {'unit': '%', 'value': '42'}, 'battery': {'unit': 'V', 'value': '1.5'}},
        'soil_ch3': {'soilmoisture': {'unit': '%', 'value': '17'}},
    })

    assert outdoor['soil_moisture_ch1'] == 42.0
    assert outdoor['soil_battery_ch1'] == 1.5
    assert 'soil_battery_ch3' not in outdoor
    assert outdoor['soil_moisture_ch3'] == 17.0
    assert 'soil_moisture_ch2' not in outdoor



def test_local_gateway_soil_payload_is_parsed():
    soil = EcowittLanIngestionDaemon._parse_local_soil({'ch_soil': [
        {'channel': '1', 'battery': '5', 'voltage': '1.70', 'humidity': '27%'},
        {'channel': '2', 'battery': '1', 'humidity': '55%'},
    ]})

    assert soil == {
        'soil_moisture_ch1': 27.0, 'soil_battery_ch1': 1.7,
        'soil_moisture_ch2': 55.0, 'soil_battery_ch2': 20.0,
    }
