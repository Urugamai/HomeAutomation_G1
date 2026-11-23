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


def test_cheap_power_window_is_weekdays_0900_to_1700():
    daemon = OcularChargerDaemon()
    in_window = datetime.datetime
    assert daemon._in_cheap_power_period(in_window(2026, 11, 23, 9, 0))  # Mon
    assert daemon._in_cheap_power_period(in_window(2026, 11, 27, 16, 59))  # Fri
    assert not daemon._in_cheap_power_period(in_window(2026, 11, 23, 8, 59))
    assert not daemon._in_cheap_power_period(in_window(2026, 11, 23, 17, 0))
    assert not daemon._in_cheap_power_period(in_window(2026, 11, 28, 12, 0))  # Sat


def test_cheap_power_charges_only_above_battery_reserve():
    daemon = OcularChargerDaemon()
    monday_noon = datetime.datetime(2026, 11, 23, 12, 0)
    daemon.battery_soc = 59
    assert daemon._target_amps(monday_noon) == 0
    daemon.battery_soc = 60
    assert daemon._target_amps(monday_noon) == daemon.CHEAP_POWER_AMPS
    assert daemon._target_amps(datetime.datetime(2026, 11, 28, 12, 0)) == 0


def test_settings_loaded_from_yaml(tmp_path):
    path = tmp_path / "charger.yml"
    path.write_text(
        "solar:\n  battery-stop-soc: 70\n"
        "cheap-power:\n  days: [sat, sun]\n  start: '22:00'\n  end: '06:00'\n"
        "  min-battery-soc: 40\n",
        encoding="utf-8",
    )
    daemon = OcularChargerDaemon(config_path=path)

    assert daemon.BATTERY_STOP_SOC == 70
    assert daemon.CHEAP_POWER_MIN_SOC == 40
    assert daemon._in_cheap_power_period(datetime.datetime(2026, 11, 28, 23, 0))
    assert daemon._in_cheap_power_period(datetime.datetime(2026, 11, 29, 5, 0))
    assert not daemon._in_cheap_power_period(datetime.datetime(2026, 12, 1, 5, 0))


def test_vehicle_soc_read_from_configured_register(tmp_path):
    path = tmp_path / "charger.yml"
    path.write_text(
        "modbus:\n  vehicle-soc:\n    register: 300\n    scale: 0.1\n",
        encoding="utf-8",
    )
    daemon = OcularChargerDaemon(config_path=path)

    class Client:
        connected = True

        def read_holding_registers(self, address, count, device_id):
            assert (address, count) == (300, 1)
            return type("R", (), {"registers": [655], "isError": lambda s: False})()

    daemon.modbus_client = Client()
    daemon._update_vehicle_soc()
    assert daemon.vehicle_soc == 65.5

    daemon.mqtt_client = FakeMqttClient()
    daemon._publish_status(datetime.datetime(2026, 11, 23, 12, 0), target_amps=0)
    assert daemon.mqtt_client.published[0][1]["vehicle_soc"] == 65.5


def test_vehicle_soc_is_none_when_register_not_configured():
    daemon = OcularChargerDaemon()
    daemon._update_vehicle_soc()
    assert daemon.vehicle_soc is None


def test_sigen_kw_feed_is_converted_to_watts():
    daemon = OcularChargerDaemon()
    message = type(
        "M", (), {
            "topic": "home/power/sigen",
            "payload": b'{"grid_flow": -4.32, "solar_power": 6.5, "battery_soc": 99}',
        },
    )()

    daemon._on_message(None, None, message)

    assert daemon.grid_flow_watts == -4320
    assert daemon.solar_power_watts == 6500
    daemon.solar_charging_active = True
    assert daemon._target_amps(datetime.datetime(2026, 11, 28, 12, 0)) == 6


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
    daemon.grid_flow_watts = -2_000

    assert daemon._target_amps() == 0

    daemon.grid_flow_watts = -4_320
    assert daemon._target_amps() == 6

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
    assert daemon.OVERRIDE_AMPS == daemon.MAX_SOLAR_AMPS
    assert writes == [32]

    daemon._set_override({"enabled": False})
    assert writes == [daemon.OVERRIDE_AMPS, 0]
