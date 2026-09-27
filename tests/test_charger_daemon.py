import datetime
import json

from controllers.charger_daemon import OcularChargerDaemon


class FakeMqttClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, json.loads(payload), qos, retain))


def test_charger_status_publishes_limits_and_commanded_state():
    daemon = OcularChargerDaemon()
    daemon.mqtt_client = FakeMqttClient()
    daemon.grid_flow_watts = -2500
    daemon.battery_soc = 74
    daemon.current_charge_rate_amps = 10

    daemon._publish_status(
        datetime.datetime(2026, 9, 27, 12, 0),
        is_off_peak=False,
        target_amps=10,
    )

    topic, payload, qos, retain = daemon.mqtt_client.published[0]
    assert topic == "home/charger/status"
    assert qos == 1
    assert retain is True
    assert payload["state"] == "Charging"
    assert payload["grid_flow_watts"] == -2500
    assert payload["limits"]["surplus_start_watts"] == -2000
    assert payload["limits"]["maximum_solar_amps"] == 32
