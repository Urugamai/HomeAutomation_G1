import time

from PyQt6.QtWidgets import QApplication

from ui.charger_page import ChargerStatusPage


def test_charger_page_displays_current_state_limits_and_chart_history():
    app = QApplication.instance() or QApplication([])
    page = ChargerStatusPage()
    status = {
        "timestamp": time.time(),
        "target_amps": 12,
        "grid_flow_watts": -2800,
        "battery_soc": 76,
        "is_override": False,
        "solar_charging_active": True,
        "limits": {
            "minimum_solar_amps": 6,
            "maximum_solar_amps": 32,
            "override_amps": 16,
            "battery_full_soc": 99,
            "battery_stop_soc": 60,
            "rate_change_interval_seconds": 600,
        },
    }

    page.refresh_status(status)

    assert page.state_label.text() == "Charger: Charging"
    assert "Command: 12 A" in page.current_label.text()
    assert "Start at 99% battery" in page.limits_label.text()
    assert page.override_button.text() == "Enable Charge Override"
    assert page.chart.samples == [(status["timestamp"], -2800.0, 76.0, 12)]
    page.resize(800, 480)
    page.show()
    app.processEvents()
    page.deleteLater()
    app.processEvents()


def test_charger_page_emits_override_command():
    app = QApplication.instance() or QApplication([])
    page = ChargerStatusPage()
    commands = []
    page.override_changed.connect(commands.append)

    page.override_button.click()

    assert commands == [True]
    page.deleteLater()
    app.processEvents()
