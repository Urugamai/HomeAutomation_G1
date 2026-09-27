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
        "is_off_peak": False,
        "limits": {
            "off_peak_amps": 16,
            "surplus_start_watts": -2000,
            "surplus_stop_watts": -2000,
            "minimum_solar_amps": 6,
            "maximum_solar_amps": 32,
            "battery_reserve_soc": 80,
        },
    }

    page.refresh_status(status)

    assert page.state_label.text() == "Charger: Charging"
    assert "Command: 12 A" in page.current_label.text()
    assert "Solar start -2000 W" in page.limits_label.text()
    assert page.chart.samples == [(status["timestamp"], -2800.0, 76.0, 12)]
    page.deleteLater()
    app.processEvents()
