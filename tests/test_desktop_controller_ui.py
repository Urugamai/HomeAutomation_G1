import datetime

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

from desk_controller import DeskControllerWindow
from libraries.mqtt_engine import MqttTelemetryListener
from ui.adaptive_ui import DesktopDashboard
from ui.cbus_floor_page import CbusFloorPage


def _application():
    return QApplication.instance() or QApplication([])


def test_desktop_dashboard_keeps_both_charts_without_clock():
    app = _application()
    dashboard = DesktopDashboard()

    dashboard.apply_hardware_profile(800, 480)
    dashboard.set_climate_samples(
        [
            {
                "timestamp": datetime.datetime.now(),
                "indoor_temperatures": {"living": 21.0},
                "outdoor_temperature": 15.0,
                "heating_setpoint": 20.0,
                "cooling_setpoint": 24.0,
                "heater_on": False,
                "cooler_on": False,
                "fan_on": False,
            }
        ]
    )

    assert dashboard.current_profile == "DESKTOP_CONTROLLER"
    assert dashboard.time_lbl.isHidden()
    assert not dashboard.power_chart.isHidden()
    assert not dashboard.climate_chart.isHidden()
    assert len(dashboard.climate_chart.samples) == 1
    dashboard._update_forecast_labels(
        [
            {
                "day_index": 0,
                "expected_min": 15.0,
                "expected_max": 23.0,
                "rain_probability": 20,
                "summary": "Partly cloudy",
            },
            {
                "day_index": 1,
                "expected_min": 14.0,
                "expected_max": 21.0,
                "rain_probability": 10,
                "summary": "Sunny",
            },
        ]
    )
    assert "<br>" not in dashboard.today_forecast_lbl.text()
    assert "<br>" not in dashboard.tomorrow_forecast_lbl.text()
    assert ":</b>" in dashboard.today_forecast_lbl.text()
    assert ":</b>" in dashboard.tomorrow_forecast_lbl.text()
    assert "Today" not in dashboard.today_forecast_lbl.text()
    assert "Tomorrow" not in dashboard.tomorrow_forecast_lbl.text()
    dashboard.refresh_telemetry_ui({"battery_soc": 76.4})
    assert dashboard.solar_widget.lbl.isHidden()
    assert dashboard.battery_widget.meter.minimumHeight() == 28
    assert "SOC 76%" in dashboard.battery_widget.meter.overlay_text
    dashboard.deleteLater()
    app.processEvents()


def test_compact_floor_controls_omit_dimmers_and_use_smaller_buttons():
    app = _application()
    commands = []
    page = CbusFloorPage(
        "Ground",
        lambda address, is_on, brightness: commands.append(
            (address, is_on, brightness)
        ),
        compact=True,
    )

    page.refresh_devices(
        {
            "56/1/1": {
                "address": "56/1/1",
                "name": "G_KITCHEN",
                "state": "ON",
                "brightness": 255,
            }
        }
    )

    button = page._buttons["56/1/1"]
    assert page._sliders == {}
    assert button.minimumHeight() == 34
    assert button.text() == "ON"

    button.click()

    assert commands == [("56/1/1", False, 0)]
    page.deleteLater()
    app.processEvents()


def test_desktop_window_uses_top_tabs_and_shared_telemetry(monkeypatch):
    app = _application()
    monkeypatch.setattr(MqttTelemetryListener, "start", lambda listener: None)
    window = DeskControllerWindow()

    assert window.tabs.tabPosition().name == "North"
    assert [
        window.tabs.tabText(index) for index in range(window.tabs.count())
    ] == ["Home", "Environment", "Ground", "First", "Charger", "Climate"]

    window._handle_telemetry_routing(
        {
            "environment_sources": {},
            "cbus_devices": {},
            "hvac_state": "OFF",
            "hvac_in_rest": False,
            "hvac_sequence_state": "OFF",
            "hvac_settings": {},
        }
    )

    assert window.ground_floor_page.compact
    assert window.first_floor_page.compact
    assert window.climate_page.climate_chart is None
    assert window._idle_timer.interval() == 5 * 60 * 1000
    display_power_calls = []
    monkeypatch.setattr(
        window,
        "_set_display_power",
        lambda enabled: display_power_calls.append(enabled),
    )
    window._sleep_display()
    assert window._display_is_sleeping
    assert not window._sleep_overlay.isHidden()
    assert window.eventFilter(None, QEvent(QEvent.Type.MouseButtonPress))
    assert not window._display_is_sleeping
    assert window._sleep_overlay.isHidden()
    assert display_power_calls == [False, True]
    window.close()
    app.processEvents()
