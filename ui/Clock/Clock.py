import argparse
import configparser
import datetime
import math
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPalette, QPen, QBrush
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget

# Allow both `python -m ui.Clock.Clock` and the existing `python Clock.py`
# launch style used by Raspberry Pi services.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
CLOCK_DIR = Path(__file__).resolve().parent
if str(CLOCK_DIR) not in sys.path:
    sys.path.insert(0, str(CLOCK_DIR))

from libraries.mqtt_engine import MqttTelemetryListener
from clock_display import Ui_MainWindow


class ZeroCenteredPowerBar(QWidget):
    """Horizontal positive/negative power bar matching the main dashboard."""

    def __init__(self, maximum_watts=5000, parent=None):
        super().__init__(parent)
        self.maximum_watts = float(maximum_watts)
        self.value_watts = 0.0
        self.setMinimumWidth(130)
        self.setMinimumHeight(28)

    def set_value(self, value_watts):
        self.value_watts = max(
            -self.maximum_watts,
            min(self.maximum_watts, float(value_watts)),
        )
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        height = self.height()
        center_x = width // 2

        painter.setPen(QPen(QColor(180, 180, 180), 1))
        painter.setBrush(QBrush(QColor(240, 240, 240)))
        painter.drawRoundedRect(0, 0, width, height, 4, 4)

        fill_width = int(
            abs(self.value_watts) / self.maximum_watts * (width / 2)
        )
        if abs(self.value_watts) < 1:
            painter.setBrush(QBrush(QColor(140, 140, 140)))
            painter.drawRect(center_x - 2, 0, 4, height)
        elif self.value_watts > 0:
            painter.setBrush(QBrush(QColor(40, 167, 69)))
            painter.drawRect(center_x, 0, fill_width, height)
        else:
            painter.setBrush(QBrush(QColor(220, 53, 69)))
            painter.drawRect(center_x - fill_width, 0, fill_width, height)

        painter.setPen(QPen(QColor(80, 80, 80), 1, Qt.PenStyle.DashLine))
        painter.drawLine(center_x, 0, center_x, height)


class ClockWindow(QMainWindow, Ui_MainWindow):
    """Wide-format clock display backed by the shared MQTT telemetry cache."""

    IDLE_TIMEOUT_SECONDS = 5 * 60

    def __init__(
        self,
        broker,
        screen_saver=False,
        idle_timeout=IDLE_TIMEOUT_SECONDS,
        wake_duration=60 * 60,
        location="rumpus",
    ):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("Home Automation Clock")
        self._apply_clock_style()
        self._replace_power_widgets()
        self.telemetry = {}
        self.screen_saver_enabled = screen_saver
        self.idle_timeout_ms = max(1, int(idle_timeout * 1000))
        self.wake_duration_ms = max(1, int(wake_duration * 1000))
        self.display_is_sleeping = False

        self._sleep_overlay = QWidget(self)
        self._sleep_overlay.setStyleSheet("background-color: black;")
        self._sleep_overlay.hide()
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._sleep_display)
        self._wake_timer = QTimer(self)
        self._wake_timer.setSingleShot(True)
        self._wake_timer.timeout.connect(self._sleep_display)
        QApplication.instance().installEventFilter(self)

        self.location = location
        self.mqtt_listener = MqttTelemetryListener(
            broker=broker,
            location=location,
        )
        self.mqtt_listener.telemetry_received.connect(self._handle_telemetry)
        self.mqtt_listener.start()

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()
        if self.screen_saver_enabled:
            self._reset_idle_timer()

    def configure_screen(self, width=None, height=None):
        screen = self.screen() or QApplication.primaryScreen()
        geometry = screen.geometry()
        target_width = min(width or geometry.width(), geometry.width())
        target_height = min(height or geometry.height(), geometry.height())
        self.resize(target_width, target_height)
        self.move(0, 0)
        if target_width == geometry.width() and target_height == geometry.height():
            self.showFullScreen()
        self._configure_visibility(target_height)
        self._configure_fonts(target_width, target_height)

    def _configure_visibility(self, height):
        self.text_clock_message.setVisible(height >= 420)
        power_visible = height >= 380
        for widget in (
            self.label_solar, self.progressBar_solar, self.label_battery,
            self.label_grid,
            self.battery_flow_bar, self.grid_flow_bar,
        ):
            widget.setVisible(power_visible)
        for widget in (
            self.label_out_temp, self.label_today, self.label_today_min,
            self.label_rain, self.label_today_rain, self.label_next,
            self.label_next_min, self.label_next_rain,
            self.label_next_rain_value,
        ):
            widget.setVisible(height >= 300)

    def _configure_fonts(self, width, height):
        date_size = max(28, int((height - 20) / 8.0))
        clock_size = max(
            42,
            min(int((height - 20) / 2.0), int((width - 4 * date_size) / 6.3)),
        )
        date_font = QFont("Courier New", date_size, QFont.Weight.Bold)
        for label in (
            self.label_day_abbrev, self.label_day, self.label_month_abbrev,
            self.label_year,
        ):
            label.setFont(date_font)
        self.label_clock_display.setFont(
            QFont("Courier New", clock_size, QFont.Weight.Bold)
        )

    def _apply_clock_style(self):
        self.setStyleSheet("QMainWindow, QWidget { background-color: black; }")
        yellow = QPalette()
        yellow.setColor(QPalette.ColorRole.WindowText, QColor(240, 240, 26))
        yellow.setColor(QPalette.ColorRole.Text, QColor(240, 240, 26))
        yellow.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0))
        for label in (
            self.label_clock_display, self.label_day_abbrev, self.label_day,
            self.label_month_abbrev, self.label_year, self.text_clock_message,
        ):
            label.setPalette(yellow)
        for label in (
            self.label_room, self.label_room_temp, self.label_room_humidity,
            self.label_room_pressure, self.label_out_temp, self.label_today,
            self.label_today_min, self.label_rain, self.label_today_rain,
            self.label_next, self.label_next_min, self.label_next_rain,
            self.label_next_rain_value, self.label_solar, self.label_battery,
            self.label_grid, self.label_value_grid,
        ):
            label.setStyleSheet("background-color: black; color: yellow;")
            label.setPalette(yellow)

    def _update_clock(self):
        now = datetime.datetime.now()
        self.label_clock_display.setText(now.strftime("%H:%M:%S"))
        self.label_day_abbrev.setText(now.strftime("%a"))
        self.label_day.setText(now.strftime("%d"))
        self.label_month_abbrev.setText(now.strftime("%b"))
        self.label_year.setText(now.strftime("%Y"))

    def _handle_telemetry(self, data):
        self.telemetry = data
        self._update_power(data)
        self._update_environment(data)
        self._update_forecast(data.get("forecast_set", []))

    def _update_power(self, data):
        solar = float(data.get("solar_power", 0.0))
        soc = max(0, min(100, int(float(data.get("battery_soc", 0.0)))))
        battery = float(data.get("battery_flow", 0.0))
        grid = float(data.get("grid_flow", 0.0))
        self.label_solar.setText(f"Solar: {solar:.0f}W")
        self.progressBar_solar.setRange(0, 100)
        self.progressBar_solar.setValue(max(0, min(100, math.ceil(solar / 100))))
        self.label_battery.setText(f"Battery: {soc}%")
        self.battery_flow_bar.set_value(battery)
        self.label_grid.setText("Grid:")
        self.grid_flow_bar.set_value(grid)

    def _replace_power_widgets(self):
        self.battery_flow_bar = ZeroCenteredPowerBar(parent=self)
        self.grid_flow_bar = ZeroCenteredPowerBar(parent=self)
        self.horizontalLayout_power.replaceWidget(
            self.progressBar_battery, self.battery_flow_bar
        )
        self.horizontalLayout_power.replaceWidget(
            self.label_value_grid, self.grid_flow_bar
        )
        self.progressBar_battery.deleteLater()
        self.label_value_grid.deleteLater()

    def _update_environment(self, data):
        room_temp = data.get("room_temp", data.get("living_temp", 0.0))
        room_humidity = data.get("room_humidity", 0.0)
        room_pressure = data.get("room_pressure", 0.0)
        outside_temp = data.get("outside_temp", 0.0)
        self.label_room_temp.setText(f"{float(room_temp):.1f}°C")
        self.label_room_humidity.setText(f"{float(room_humidity):.1f}%")
        self.label_room_pressure.setText(f"{float(room_pressure):.0f} hPa")
        self.label_out_temp.setText(f"Outside: {float(outside_temp):.1f}°C")

    def _update_forecast(self, forecasts):
        today = next((item for item in forecasts if item.get("day_index") == 0), None)
        tomorrow = next((item for item in forecasts if item.get("day_index") == 1), None)
        if today:
            self._set_forecast_row(
                self.label_today, self.label_today_min, self.label_today_rain,
                "Today:", today
            )
        if tomorrow:
            self._set_forecast_row(
                self.label_next, self.label_next_min, self.label_next_rain_value,
                "Next:", tomorrow
            )

    @staticmethod
    def _temperature_range(item):
        minimum = item.get("expected_min")
        maximum = item.get("expected_max")
        if minimum is None and maximum is None:
            return "--°C"
        if minimum is None:
            return f"{float(maximum):.1f}°C"
        if maximum is None:
            return f"{float(minimum):.1f}°C"
        return f"{float(minimum):.1f} → {float(maximum):.1f}°C"

    def _set_forecast_row(self, date_label, range_label, rain_label, title, item):
        date_label.setText(title)
        range_label.setText(self._temperature_range(item))
        probability = item.get("rain_probability")
        if probability is None:
            rain_label.setText("Rain: --%")
            return
        probability = max(0, min(100, int(float(probability))))
        rain_label.setText(f"Rain: {probability}%")
        rain_label.setStyleSheet(
            f"background-color: rgb({255}, {255 - probability}, {255 - probability});"
        )

    def eventFilter(self, watched, event):
        if event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.TouchBegin,
            QEvent.Type.KeyPress,
        ):
            if self.screen_saver_enabled:
                if self.display_is_sleeping:
                    self._wake_display()
                else:
                    self._reset_idle_timer()
        return super().eventFilter(watched, event)

    def _reset_idle_timer(self):
        if not self.display_is_sleeping:
            self._wake_timer.stop()
            self._idle_timer.start(self.idle_timeout_ms)

    def _sleep_display(self):
        if not self.screen_saver_enabled:
            return
        self.display_is_sleeping = True
        self._idle_timer.stop()
        self._wake_timer.stop()
        self._sleep_overlay.setGeometry(self.rect())
        self._sleep_overlay.raise_()
        self._sleep_overlay.show()

    def _wake_display(self):
        self._sleep_overlay.hide()
        self.display_is_sleeping = False
        self._idle_timer.stop()
        self._wake_timer.start(self.wake_duration_ms)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self._idle_timer.stop()
        self._wake_timer.stop()
        self._clock_timer.stop()
        self.mqtt_listener.stop()
        super().closeEvent(event)


def _load_broker():
    config = configparser.ConfigParser()
    config.read(Path(__file__).resolve().parents[2] / "config.ini")
    return config.get("MQTT", "broker", fallback="localhost")


def main():
    parser = argparse.ArgumentParser(description="Home Automation MQTT clock")
    parser.add_argument("--broker", default=None)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--screen-saver", action="store_true")
    parser.add_argument("--idle-seconds", type=int, default=5 * 60)
    parser.add_argument("--wake-seconds", type=int, default=60 * 60)
    parser.add_argument(
        "--location",
        default="rumpus",
        help="Room telemetry topic suffix, e.g. rumpus or bathroom",
    )
    args = parser.parse_args()

    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    app = QApplication(sys.argv)
    window = ClockWindow(
        broker=args.broker or _load_broker(),
        screen_saver=args.screen_saver,
        idle_timeout=args.idle_seconds,
        wake_duration=args.wake_seconds,
        location=args.location,
    )
    window.configure_screen(args.width, args.height)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
