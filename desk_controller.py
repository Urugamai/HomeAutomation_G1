"""Desktop controller entry point for the fixed 800x480 display."""

import configparser
import logging
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QEvent, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QWidget,
)

from libraries.mqtt_engine import MqttTelemetryListener
from main import _load_power_chart_grid_interval
from ui.adaptive_ui import DesktopDashboard, EnvironmentSourcesPage
from ui.cbus_floor_page import CbusFloorPage
from ui.charger_page import ChargerStatusPage
from ui.hvac_page import HvacConfigurationPage

LOGGER = logging.getLogger(__name__)


class DeskControllerWindow(QMainWindow):
    """Controller window tailored to a fixed 800x480 desktop display."""

    DISPLAY_IDLE_TIMEOUT_MS = 5 * 60 * 1000

    def __init__(self, broker_ip="localhost", power_chart_grid_interval_hours=1):
        super().__init__()
        self.setWindowTitle("Home Automation Desktop Controller")
        self.setMinimumSize(800, 480)
        self._display_is_sleeping = False
        self._sleep_overlay = QWidget(self)
        self._sleep_overlay.setStyleSheet("background-color: black;")
        self._sleep_overlay.hide()
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._sleep_display)
        QApplication.instance().installEventFilter(self)

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
        self.charger_page = ChargerStatusPage()
        self.tabs.addTab(self.charger_page, "Charger")
        self.climate_page = HvacConfigurationPage(show_climate_chart=False)
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
        self._reset_idle_timer()

    def showEvent(self, event):
        super().showEvent(event)
        self.dashboard.apply_hardware_profile(800, 480, self.tabs)

    def _handle_telemetry_routing(self, data):
        self.dashboard.refresh_telemetry_ui(data)
        self.environment_page.refresh_sources(data.get("environment_sources", {}))
        cbus_devices = data.get("cbus_devices", {})
        self.ground_floor_page.refresh_devices(cbus_devices)
        self.first_floor_page.refresh_devices(cbus_devices)
        self.charger_page.refresh_status(data.get("charger_status", {}))
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

    def eventFilter(self, watched, event):
        input_events = {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.TouchBegin,
            QEvent.Type.KeyPress,
        }
        if event.type() in input_events:
            if self._display_is_sleeping:
                self._wake_display()
                return True
            else:
                self._reset_idle_timer()
        return super().eventFilter(watched, event)

    def _reset_idle_timer(self):
        if not self._display_is_sleeping:
            self._idle_timer.start(self.DISPLAY_IDLE_TIMEOUT_MS)

    def _sleep_display(self):
        self._display_is_sleeping = True
        self._idle_timer.stop()
        self._sleep_overlay.setGeometry(self.rect())
        self._sleep_overlay.raise_()
        self._sleep_overlay.show()
        self._set_display_power(False)

    def _wake_display(self):
        self._set_display_power(True)
        self._sleep_overlay.hide()
        self._display_is_sleeping = False
        self._reset_idle_timer()

    @staticmethod
    def _set_display_power(enabled):
        if not sys.platform.startswith("linux"):
            return

        power = "1" if enabled else "0"
        commands = (
            ["vcgencmd", "display_power", power],
            ["xset", "dpms", "force", "on" if enabled else "off"],
        )
        for command in commands:
            executable = shutil.which(command[0])
            if executable is None:
                continue
            try:
                subprocess.run(
                    [executable, *command[1:]],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return
            except (OSError, subprocess.SubprocessError) as error:
                LOGGER.warning(
                    "Display power command failed (%s): %s",
                    " ".join(command),
                    error,
                )

        LOGGER.warning(
            "No working display power command was available; "
            "using the software sleep overlay only"
        )

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self._idle_timer.stop()
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
