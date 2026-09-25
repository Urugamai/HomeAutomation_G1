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
