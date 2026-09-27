"""Desktop controller entry point for the fixed 800x480 display."""

import configparser
import os
import socket
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTabWidget,
)

from libraries.mqtt_engine import MqttTelemetryListener
from main import _load_power_chart_grid_interval
from ui.adaptive_ui import DesktopDashboard, EnvironmentSourcesPage
from ui.cbus_floor_page import CbusFloorPage
from ui.hvac_page import HvacConfigurationPage


class DeskControllerWindow(QMainWindow):
    """Controller window tailored to a fixed 800x480 desktop display."""

    def __init__(self, broker_ip="localhost", power_chart_grid_interval_hours=1):
        super().__init__()
        self.setWindowTitle("Home Automation Desktop Controller")
        self.setMinimumSize(800, 480)

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setStyleSheet(
            """
            QTabBar::tab {
                height: 32px;
                min-width: 100px;
                font-size: 10pt;
                font-weight: bold;
                padding: 3px 8px;
            }
            """
        )

        self.dashboard = DesktopDashboard(power_chart_grid_interval_hours)
        self.tabs.addTab(self.dashboard, "Home")
        self.environment_page = EnvironmentSourcesPage()
        self.tabs.addTab(self.environment_page, "Environment")
        self.ground_floor_page = CbusFloorPage(
            "Ground", self._set_cbus_device, compact=True
        )
        self.tabs.addTab(self.ground_floor_page, "Ground")
        self.first_floor_page = CbusFloorPage(
            "First", self._set_cbus_device, compact=True
        )
        self.tabs.addTab(self.first_floor_page, "First")
        self.climate_page = HvacConfigurationPage()
        self.tabs.addTab(self.climate_page, "Climate")
        self.setCentralWidget(self.tabs)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.hvac_status_label = QLabel("System State: Idle (OFF)")
        self.status_bar.addWidget(self.hvac_status_label, 1)
        self.connection_status_label = QLabel("Initializing system connection...")
        self.status_bar.addPermanentWidget(self.connection_status_label)
        if sys.platform == "win32":
            exit_button = QPushButton("Exit")
            exit_button.clicked.connect(QApplication.instance().quit)
            self.status_bar.addPermanentWidget(exit_button)

        self.mqtt_listener = MqttTelemetryListener(
            broker=broker_ip,
            location=socket.gethostname(),
        )
        self.mqtt_listener.telemetry_received.connect(self._handle_telemetry_routing)
        self.climate_page.settings_changed.connect(self.mqtt_listener.set_hvac_settings)
        self.climate_page.command_requested.connect(self.mqtt_listener.set_hvac_command)
        self.climate_page.status_changed.connect(self.hvac_status_label.setText)
        self.climate_page.climate_history_updated.connect(
            self.dashboard.set_climate_samples
        )
        self.dashboard.set_climate_samples(self.climate_page.climate_history.samples)
        self.mqtt_listener.start()

        if self.mqtt_listener.is_windows:
            self.connection_status_label.setText("Simulated Data Mode (Offline Testing)")
        else:
            self.connection_status_label.setText("Live Data Mode (Connected to MQ)")

    def showEvent(self, event):
        super().showEvent(event)
        self.dashboard.apply_hardware_profile(800, 480, self.tabs)

    def _handle_telemetry_routing(self, data):
        self.dashboard.refresh_telemetry_ui(data)
        self.environment_page.refresh_sources(data.get("environment_sources", {}))
        cbus_devices = data.get("cbus_devices", {})
        self.ground_floor_page.refresh_devices(cbus_devices)
        self.first_floor_page.refresh_devices(cbus_devices)
        self.climate_page.update_status_from_mqtt(
            data.get("hvac_state", "OFF"),
            data.get("hvac_in_rest", False),
            data.get("hvac_sequence_state", "OFF"),
            data.get("heater_relay_on", False),
            data.get("cooler_relay_on", False),
            data.get("fan_relay_on", False),
            data.get("hvac_pending_state"),
            data.get("hvac_transition_ends_at"),
        )
        self.climate_page.apply_settings(data.get("hvac_settings", {}))
        self.climate_page.update_climate_telemetry(data)

    def _set_cbus_device(self, address, is_on, brightness):
        self.mqtt_listener.set_cbus_device(address, is_on, brightness)

    def closeEvent(self, event):
        self.mqtt_listener.stop()
        super().closeEvent(event)


def _broker_ip():
    config_file = Path(__file__).resolve().parent / "config.ini"
    config = configparser.ConfigParser()
    if config_file.exists():
        config.read(config_file)
    return config.get("MQTT", "broker", fallback="localhost")


def main():
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    window = DeskControllerWindow(
        broker_ip=_broker_ip(),
        power_chart_grid_interval_hours=_load_power_chart_grid_interval(
            socket.gethostname()
        ),
    )
    window.showFullScreen()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
