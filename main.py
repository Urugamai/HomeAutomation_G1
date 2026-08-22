import sys
import os
import configparser
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget
from ui.adaptive_ui import AdaptiveDashboard
from libraries.mqtt_engine import MqttTelemetryListener


class MainWindow(QMainWindow):
    def __init__(self, broker_ip="localhost"):
        super().__init__()
        self.setWindowTitle("Smart Automation Terminal Node")

        self.tabs = QTabWidget()
        self.dashboard = AdaptiveDashboard()
        self.tabs.addTab(self.dashboard, "Status Core")
        self.setCentralWidget(self.tabs)

        # Bind the pure PyQt6 network client to your dashboard layout
        self.mqtt_listener = MqttTelemetryListener(broker=broker_ip)
        self.mqtt_listener.telemetry_received.connect(self.dashboard.refresh_telemetry_ui)
        self.mqtt_listener.start()

    def showEvent(self, event):
        super().showEvent(event)
        screen_geom = QApplication.primaryScreen().geometry()
        self.dashboard.apply_hardware_profile(screen_geom.width(), screen_geom.height(), parent_tab_widget=self.tabs)

    def closeEvent(self, event):
        self.mqtt_listener.stop()
        super().closeEvent(event)


def main():
    # Fix scaling layouts on high-DPI Windows 11 monitors
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

    app = QApplication(sys.argv)
    window = MainWindow(broker_ip=broker_ip)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
