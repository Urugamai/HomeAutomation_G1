import time
import datetime

from PyQt6.QtWidgets import QApplication

from ui.hvac_page import HvacConfigurationPage


def test_average_house_temperature_display_uses_hvac_average():
    app = QApplication.instance() or QApplication([])
    page = HvacConfigurationPage()

    page.update_climate_telemetry({"hvac_temperature": 21.75})

    assert page.average_house_temp_lbl.text() == "21.8 °C"
    page.deleteLater()
    app.processEvents()


def test_average_house_temperature_display_falls_back_to_indoor_sources():
    app = QApplication.instance() or QApplication([])
    page = HvacConfigurationPage()

    page.update_climate_telemetry(
        {
            "environment_sources": {
                "living": {"temperature": 20.0},
                "upstairs": {"temperature": 22.0},
                "Ecowitt": {"temperature": 5.0},
            }
        }
    )

    assert page.average_house_temp_lbl.text() == "21.0 °C"
    page.deleteLater()
    app.processEvents()


def test_relay_buttons_display_precool_and_postrun_countdowns():
    app = QApplication.instance() or QApplication([])
    page = HvacConfigurationPage()

    page.update_status_from_mqtt(
        "OFF",
        False,
        "MANUAL_PREHEAT",
        False,
        False,
        True,
        "COOLING",
        time.time() + 30,
    )

    assert page.cooler_relay_indicator.text().startswith("Cooler\nOFF-PreCool\n")
    assert page.fan_relay_indicator.text().startswith("Fan\nON-PreCool\n")

    page.update_status_from_mqtt(
        "OFF",
        False,
        "MANUAL_POSTRUN",
        False,
        False,
        True,
        None,
        time.time() + 30,
    )

    assert page.fan_relay_indicator.text().startswith("Fan\nON-PostRun\n")
    page.deleteLater()
    app.processEvents()


def test_vacation_dates_follow_calendar_selection_rules():
    app = QApplication.instance() or QApplication([])
    page = HvacConfigurationPage()
    page.vacation_start = None
    page.vacation_end = None
    today = datetime.date.today()

    page._select_vacation_date(today)
    assert page.vacation_start == today
    assert page.vacation_end is None

    page._select_vacation_date(today + datetime.timedelta(days=7))
    assert page.vacation_end == today + datetime.timedelta(days=7)
    assert "Vacation start" in page.vacation_status_lbl.text()

    page._select_vacation_date(today + datetime.timedelta(days=3))
    assert page.vacation_start == today + datetime.timedelta(days=3)

    page._select_vacation_date(today + datetime.timedelta(days=10))
    assert page.vacation_end == today + datetime.timedelta(days=10)
    page.vacation_start_time = datetime.time(hour=16, minute=30)
    page.vacation_end_time = datetime.time(hour=10, minute=15)
    assert page._settings_payload()["vacation_start_time"] == "16:30"
    assert page._settings_payload()["vacation_end_time"] == "10:15"
    page.deleteLater()
    app.processEvents()


def test_empty_house_schedule_displays_adjusted_pause_window():
    app = QApplication.instance() or QApplication([])
    page = HvacConfigurationPage()

    page._set_empty_house_schedule(
        datetime.time(hour=10),
        datetime.time(hour=16),
    )

    payload = page._settings_payload()
    assert payload["empty_house_date"] == datetime.date.today().isoformat()
    assert payload["empty_house_start_time"] == "10:00"
    assert payload["empty_house_end_time"] == "16:00"
    assert "10:30 through 15:00" in page.empty_house_status_lbl.text()
    page.deleteLater()
    app.processEvents()
