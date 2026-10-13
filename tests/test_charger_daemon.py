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
        target_amps=10,
    )

    topic, payload, qos, retain = daemon.mqtt_client.published[0]
    assert topic == "home/charger/status"
    assert qos == 1
    assert retain is True
    assert payload["state"] == "Charging"
    assert payload["grid_flow_watts"] == -2500
    assert payload["limits"]["maximum_solar_amps"] == 32
    assert payload["limits"]["battery_full_soc"] == 99
    assert payload["limits"]["battery_stop_soc"] == 60


def test_solar_charging_latches_at_full_battery_until_low_soc():
    daemon = OcularChargerDaemon()
    daemon.battery_soc = 99

    daemon._update_solar_charging_state()

    assert daemon.solar_charging_active is True

    daemon.battery_soc = 60
    daemon._update_solar_charging_state()
    assert daemon.solar_charging_active is True

    daemon.battery_soc = 59.9
    daemon._update_solar_charging_state()
    assert daemon.solar_charging_active is False


def test_solar_target_uses_grid_export_feedback_and_three_phase_power():
    daemon = OcularChargerDaemon()
    daemon.solar_charging_active = True
    daemon.current_charge_rate_amps = 6
    daemon.grid_flow_watts = -2_000

    assert daemon._target_amps() == 8

    daemon.grid_flow_watts = 1_000
    assert daemon._target_amps() == 6


def test_automatic_rate_change_waits_ten_minutes(monkeypatch):
    daemon = OcularChargerDaemon()
    writes = []
    daemon._write_modbus_rate = lambda amps: writes.append(amps) or True
    clock = [1_000.0]
    monkeypatch.setattr("controllers.charger_daemon.time.time", lambda: clock[0])

    daemon._request_rate(6)
    clock[0] += 599
    daemon._request_rate(8)
    clock[0] += 1
    daemon._request_rate(8)

    assert writes == [6, 8]


def test_retained_override_forces_configured_charging_rate():
    daemon = OcularChargerDaemon()
    writes = []
    daemon._write_modbus_rate = lambda amps: writes.append(amps) or True

    daemon._set_override({"enabled": True})

    assert daemon.override_enabled is True
    assert writes == [daemon.OVERRIDE_AMPS]

    daemon._set_override({"enabled": False})
    assert writes == [daemon.OVERRIDE_AMPS, 0]
