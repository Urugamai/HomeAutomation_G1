import sys
import os
import time
import configparser
import traceback
from pathlib import Path
from PyQt6.QtCore import QEvent, QTimer
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QStatusBar, QPushButton, QWidget)

# Cross-package import targets matching your project layout schema
from ui.adaptive_ui import AdaptiveDashboard
from libraries.mqtt_engine import MqttTelemetryListener


# Open main.py and locate the __init__ constructor inside the MainWindow class:

class MainWindow(QMainWindow):
    DISPLAY_IDLE_TIMEOUT_MS = 5 * 60 * 1000

    # Open main.py and place this stylesheet assignment right inside MainWindow.__init__:

    def __init__(self, broker_ip="localhost"):
        super().__init__()
        self.setWindowTitle("Smart Automation Terminal Node")
        self._display_is_sleeping = False
        self._sleep_overlay = QWidget(self)
        self._sleep_overlay.setStyleSheet("background-color: black;")
        self._sleep_overlay.hide()
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._sleep_display)
        QApplication.instance().installEventFilter(self)

        self.tabs = QTabWidget()

        # FIXED: Enforce a thumb-friendly touchscreen tab footprint with a fatter layout style sheet
        self.tabs.setStyleSheet("""
                QTabBar::tab {
                    height: 55px;
                    min-width: 150px;
                    font-size: 14pt;
                    font-weight: bold;
                    padding: 5px;
                }
            """)

        self.dashboard = AdaptiveDashboard()
        self.tabs.addTab(self.dashboard, "Status Core")
        self.setCentralWidget(self.tabs)

        # ... Rest of your main.py constructor lines continue exactly as before ...

        # 2. Append the structural status bar elements
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Initializing system connection profile...")
        if sys.platform == "win32":
            self.exit_button = QPushButton("Exit")
            self.exit_button.setToolTip("Exit the testing display")
            self.exit_button.clicked.connect(QApplication.instance().quit)
            self.status_bar.addPermanentWidget(self.exit_button)

        # 3. FIXED: Force the application frame to draw without window borders in full screen
        self.showFullScreen()  # <--- REMOVE ANY LATER .show() AND CALL THIS INSIDE THE CONSTRUCTOR

        # 4. Initialize and bind the environment-aware listener engine
        self.mqtt_listener = MqttTelemetryListener(broker=broker_ip)
        self.mqtt_listener.telemetry_received.connect(self._handle_telemetry_routing)
        self.mqtt_listener.start()

        # Query the operational mode flag state immediately to update the footer message
        if self.mqtt_listener.is_windows:
            self.status_bar.showMessage("Simulated Data Mode (Offline Testing)")
            self.status_bar.setStyleSheet("background-color: #fff3cd; color: #856404; font-weight: bold;")
        else:
            self.status_bar.showMessage("Live Data Mode (Connected to MQ)")
            self.status_bar.setStyleSheet("background-color: #d4edda; color: #155724; font-weight: bold;")
        self._reset_idle_timer()

    def showEvent(self, event):
        super().showEvent(event)
        screen_geom = QApplication.primaryScreen().geometry()
        self.dashboard.apply_hardware_profile(screen_geom.width(), screen_geom.height(), parent_tab_widget=self.tabs)

    def _handle_telemetry_routing(self, data: dict):
        self.dashboard.refresh_telemetry_ui(data)
        if self.dashboard.hvac_config_tab:
            current_run_state = data.get("hvac_state", "OFF")
            is_resting = data.get("hvac_in_rest", False)
            self.dashboard.hvac_config_tab.update_status_from_mqtt(current_run_state, is_resting)

    def eventFilter(self, watched, event):
        input_events = {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.TouchBegin,
            QEvent.Type.KeyPress,
        }
        if event.type() in input_events:
            if self._display_is_sleeping:
                self._wake_display()
            else:
                self._reset_idle_timer()
        return super().eventFilter(watched, event)

    def _reset_idle_timer(self):
        if not self._display_is_sleeping:
            self._idle_timer.start(self.DISPLAY_IDLE_TIMEOUT_MS)

    def _sleep_display(self):
        self._display_is_sleeping = True
        self._sleep_overlay.setGeometry(self.rect())
        self._sleep_overlay.raise_()
        self._sleep_overlay.show()

    def _wake_display(self):
        self._sleep_overlay.hide()
        self._display_is_sleeping = False
        self._reset_idle_timer()

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self._idle_timer.stop()
        self.mqtt_listener.stop()
        super().closeEvent(event)


def main():
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    config_file = Path(__file__).resolve().parent / "config.ini"
    broker_ip = "localhost"
    if config_file.exists():
        try:
            config = configparser.ConfigParser()
            config.read(str(config_file))
            broker_ip = config.get("MQTT", "broker", fallback="localhost")
        except Exception:
            pass

    max_restart_attempts = 10
    restart_count = 0
    restart_delay = 5  # seconds

    while restart_count < max_restart_attempts:
        try:
            app = QApplication(sys.argv)
            window = MainWindow(broker_ip=broker_ip)
            window.show()
            
            # If exec() returns normally, exit without restart
            result = app.exec()
            sys.exit(result)
            
        except Exception as e:
            restart_count += 1
            error_msg = f"UI crashed (attempt {restart_count}/{max_restart_attempts}): {str(e)}"
            print(f"[ERROR] {error_msg}")
            print(f"[TRACEBACK] {traceback.format_exc()}")
            
            if restart_count < max_restart_attempts:
                print(f"[RESTART] Attempting to restart UI in {restart_delay} seconds...")
                time.sleep(restart_delay)
                # Increase delay with each restart to prevent rapid crash loops
                restart_delay = min(restart_delay * 2, 60)
            else:
                print(f"[FATAL] Max restart attempts reached. Exiting.")
                sys.exit(1)


if __name__ == "__main__":
    main()
