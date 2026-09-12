import argparse
import configparser
import datetime
import logging
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QPainter, QPalette, QPen, QBrush,
)
from PyQt6.QtWidgets import (
    QApplication, QLayout, QMainWindow, QSizePolicy, QWidget,
)

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

LOGGER = logging.getLogger(__name__)
CLOCK_HOST_CONFIG_PATH = REPO_ROOT / "config" / "clock-host-config.yml"


@dataclass(frozen=True)
class ClockHostSchedule:
    turn_on: datetime.time
    turn_off: datetime.time
    touch_on_duration: datetime.timedelta

    def is_scheduled_on(self, current_time: datetime.time) -> bool:
        if self.turn_on <= self.turn_off:
            return self.turn_on <= current_time < self.turn_off
        return current_time >= self.turn_on or current_time < self.turn_off


def _parse_clock_time(value, field_name):
    text = str(value).strip()
    if ":" in text:
        parsed = datetime.datetime.strptime(text, "%H:%M").time()
    else:
        if not text.isdigit() or len(text) not in (3, 4):
            raise ValueError(f"{field_name} must use HHMM or HH:MM format")
        text = text.zfill(4)
        parsed = datetime.datetime.strptime(text, "%H%M").time()
    return parsed


def _load_clock_host_schedule(hostname):
    if not CLOCK_HOST_CONFIG_PATH.exists():
        return None

    try:
        import yaml
    except ImportError as exc:
        LOGGER.error(
            "Cannot load %s because PyYAML is not installed",
            CLOCK_HOST_CONFIG_PATH,
        )
        raise RuntimeError("PyYAML is required for clock-host-config.yml") from exc

    try:
        with CLOCK_HOST_CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            config = yaml.load(config_file, Loader=yaml.BaseLoader) or {}
        settings = config.get(hostname)
        if settings is None:
            return None
        if not isinstance(settings, dict):
            raise ValueError(f"{hostname} must contain a mapping of settings")

        turn_on = _parse_clock_time(settings["turn-on"], "turn-on")
        turn_off = _parse_clock_time(settings["turn-off"], "turn-off")
        touch_minutes = int(settings["touch-on-duration"])
        if touch_minutes < 0:
            raise ValueError("touch-on-duration must not be negative")
        return ClockHostSchedule(
            turn_on=turn_on,
            turn_off=turn_off,
            touch_on_duration=datetime.timedelta(minutes=touch_minutes),
        )
    except (KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        LOGGER.error(
            "Invalid clock host configuration for %s in %s: %s",
            hostname,
            CLOCK_HOST_CONFIG_PATH,
            exc,
        )
        raise


class ZeroCenteredPowerBar(QWidget):
    """Power/status bar with optional percentage fill and embedded text."""

    def __init__(
        self,
        maximum_kw=5.0,
        percentage_fill=False,
        bordered=False,
        parent=None,
    ):
        super().__init__(parent)
        self.maximum_kw = float(maximum_kw)
        self.value_kw = 0.0
        self.percentage_fill = percentage_fill
        self.bordered = bordered
        self.fill_percent = 0.0
        self.display_text = ""
        self.setMinimumWidth(220)
        self.setFixedHeight(34)

    def set_value(self, value_kw):
        self.value_kw = max(
            -self.maximum_kw,
            min(self.maximum_kw, float(value_kw)),
        )
        self.update()

    def set_percentage(self, percentage, display_text):
        self.fill_percent = max(0.0, min(100.0, float(percentage)))
        self.display_text = display_text
        self.update()

    def set_flow(self, value_kw, display_text):
        self.set_value(value_kw)
        self.display_text = display_text

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        height = self.height()
        center_x = width // 2

        painter.setPen(QPen(QColor(180, 180, 180), 1))
        painter.setBrush(QBrush(QColor(240, 240, 240)))
        painter.drawRoundedRect(0, 0, width, height, 4, 4)

        if self.percentage_fill:
            fill_width = int(self.fill_percent / 100 * width)
            painter.setBrush(QBrush(QColor(40, 167, 69)))
            painter.drawRect(0, 0, fill_width, height)
        else:
            fill_width = int(
                abs(self.value_kw) / self.maximum_kw * (width / 2)
            )
            if abs(self.value_kw) < 0.01:
                painter.setBrush(QBrush(QColor(140, 140, 140)))
                painter.drawRect(center_x - 2, 0, 4, height)
            elif self.value_kw > 0:
                painter.setBrush(QBrush(QColor(40, 167, 69)))
                painter.drawRect(center_x, 0, fill_width, height)
            else:
                painter.setBrush(QBrush(QColor(220, 53, 69)))
                painter.drawRect(center_x - fill_width, 0, fill_width, height)

            painter.setPen(QPen(QColor(80, 80, 80), 1, Qt.PenStyle.DashLine))
            painter.drawLine(center_x, 0, center_x, height)

        if self.bordered:
            painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            painter.setPen(QPen(QColor(80, 80, 80), 2))
            painter.drawRoundedRect(1, 1, width - 2, height - 2, 4, 4)

        painter.setPen(QColor(0, 0, 0))
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignCenter,
            self.display_text,
        )


class ClockWindow(QMainWindow, Ui_MainWindow):
    """Wide-format clock display backed by the shared MQTT telemetry cache."""

    IDLE_TIMEOUT_SECONDS = 5 * 60
    REFERENCE_WIDTH = 1600
    REFERENCE_HEIGHT = 600
    REFERENCE_CLOCK_SIZE = 230
    REFERENCE_DATE_SIZE = 52
    REFERENCE_INFO_SIZE = 26

    def __init__(
        self,
        broker,
        screen_saver=False,
        idle_timeout=IDLE_TIMEOUT_SECONDS,
        wake_duration=60 * 60,
        location=None,
        host_schedule=None,
    ):
        super().__init__()
        self._layout_ready = False
        self._configuring_screen = False
        self.setupUi(self)
        self.setWindowTitle("Home Automation Clock")
        window_flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        if sys.platform.startswith("linux"):
            window_flags |= Qt.WindowType.X11BypassWindowManagerHint
        self.setWindowFlags(window_flags)
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BlankCursor))
        self._cursor_hidden = True
        self._apply_clock_style()
        self._replace_power_widgets()
        self.telemetry = {}
        self.screen_saver_enabled = screen_saver
        self.host_schedule = host_schedule
        self._touch_wake_until = None
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
        self._schedule_timer = QTimer(self)
        self._schedule_timer.timeout.connect(self._update_schedule)
        if self.host_schedule:
            self._schedule_timer.start(1000)
        QApplication.instance().installEventFilter(self)

        self.location = location or socket.gethostname()
        self.mqtt_listener = MqttTelemetryListener(
            broker=broker,
            location=self.location,
        )
        self.mqtt_listener.telemetry_received.connect(self._handle_telemetry)
        self.mqtt_listener.start()

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()
        self._layout_ready = True
        if self.screen_saver_enabled and not self.host_schedule:
            self._reset_idle_timer()
        if self.host_schedule:
            self._update_schedule()

    def configure_screen(self, width=None, height=None):
        screen = self.screen() or QApplication.primaryScreen()
        geometry = screen.geometry()
        target_width = min(width or geometry.width(), geometry.width())
        target_height = min(height or geometry.height(), geometry.height())
        self._configure_layout()
        self._configure_visibility(target_height)
        self._configure_fonts(target_width, target_height)
        self._configuring_screen = True
        self.resize(target_width, target_height)
        self._configuring_screen = False
        self.move(0, 0)

    def force_fullscreen(self):
        screen = self.screen() or QApplication.primaryScreen()
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()

    def _configure_visibility(self, height):
        compact = height <= 420
        self.text_clock_message.setVisible(not compact)
        power_visible = height >= 360
        for widget in (
            self.solar_power_bar, self.battery_power_bar, self.grid_power_bar,
        ):
            widget.setVisible(power_visible)
        for widget in (
            self.label_room_humidity, self.label_room_pressure,
        ):
            widget.setVisible(not compact)
        for widget in (
            self.label_day_abbrev, self.label_day, self.label_month_abbrev,
            self.label_year,
        ):
            widget.setVisible(True)
        self.label_room.setVisible(True)
        self.label_room_temp.setVisible(True)
        self.label_out_temp.setVisible(True)
        for widget in (
            self.label_out_temp, self.label_today, self.label_today_min,
            self.label_rain, self.label_today_rain, self.label_next,
            self.label_next_min, self.label_next_rain,
            self.label_next_rain_value,
        ):
            widget.setVisible(height >= 300)

    def _configure_layout(self):
        for layout in (
            self.verticalLayout,
            self.verticalLayout_main,
            self.horizontalLayout_clock_date,
            self.verticalLayout_ClockDisplay,
            self.verticalLayout_date,
            self.horizontalLayout_power,
            self.horizontalLayout_environment_main,
            self.horizontalLayout_room_stats,
        ):
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        for label in (
            self.label_room, self.label_room_temp, self.label_room_humidity,
            self.label_room_pressure, self.label_out_temp, self.label_today,
            self.label_today_min, self.label_today_rain, self.label_next,
            self.label_next_min, self.label_next_rain,
            self.label_next_rain_value,
        ):
            policy = label.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
            label.setSizePolicy(policy)
        for label in (self.label_room_humidity, self.label_room_pressure):
            label.setMaximumSize(16777215, 16777215)
        for index in range(self.horizontalLayout_environment_main.count()):
            item = self.horizontalLayout_environment_main.itemAt(index)
            spacer = item.spacerItem()
            if spacer is not None:
                spacer.changeSize(
                    6, 0,
                    QSizePolicy.Policy.Fixed,
                    QSizePolicy.Policy.Minimum,
                )
        self.statusbar.hide()
        self.label_clock_display.setMinimumHeight(0)
        self.verticalLayout_date.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.label_solar.hide()
        self.label_battery.hide()
        self.label_grid.hide()
        self.progressBar_solar.hide()
        self.battery_flow_bar.hide()
        self.grid_flow_bar.hide()
        self.label_clock_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for label in (
            self.label_day_abbrev, self.label_day, self.label_month_abbrev,
            self.label_year,
        ):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _configure_fonts(self, width, height):
        scale = min(
            width / self.REFERENCE_WIDTH,
            height / self.REFERENCE_HEIGHT,
        )
        date_size = max(18, min(self.REFERENCE_DATE_SIZE, round(
            self.REFERENCE_DATE_SIZE * scale
        )))
        if height <= 420:
            date_size = max(18, round(date_size * 0.82))
        date_font = QFont("Courier New", date_size, QFont.Weight.Bold)
        date_font_metrics = QFontMetrics(date_font)
        date_width = date_font_metrics.horizontalAdvance("2026") + 8
        available_clock_width = max(32, width - date_width - 4)
        clock_size = min(
            round(self.REFERENCE_CLOCK_SIZE * scale),
            int(height * 0.45),
        )
        while clock_size > 32:
            self.label_clock_display.setFont(
                QFont("Courier New", clock_size, QFont.Weight.Bold)
            )
            if self.label_clock_display.sizeHint().width() <= available_clock_width:
                break
            clock_size -= 1
        info_scale = min(
            width / self.REFERENCE_WIDTH,
            max(height, 480) / self.REFERENCE_HEIGHT,
        )
        if height <= 420:
            info_size = max(10, min(24, round(self.REFERENCE_INFO_SIZE * info_scale)))
        else:
            info_size = max(10, min(28, round(self.REFERENCE_INFO_SIZE * info_scale)))
        power_size = max(16, min(30, round(28 * info_scale)))
        message_size = max(10, min(16, round(16 * scale)))
        self.progressBar_solar.setMaximumWidth(
            max(100, min(240, round(width * 0.15)))
        )

        for label in (
            self.label_day_abbrev, self.label_day, self.label_month_abbrev,
            self.label_year,
        ):
            label.setFont(date_font)
            label.setFixedWidth(date_width)
            label.setFixedHeight(date_font_metrics.height() + 2)
        self.label_clock_display.setFont(
            QFont("Courier New", clock_size, QFont.Weight.Bold)
        )
        clock_height = QFontMetrics(self.label_clock_display.font()).height() + 6
        if height <= 420:
            clock_height = max(clock_height, 230)
        self.label_clock_display.setFixedHeight(clock_height)
        date_height = date_font_metrics.height() + 2
        if height <= 420:
            date_height = max(date_height, clock_height // 4)
        for label in (
            self.label_day_abbrev, self.label_day, self.label_month_abbrev,
            self.label_year,
        ):
            label.setFixedHeight(date_height)
        self.text_clock_message.setFont(
            QFont("Courier New", message_size, QFont.Weight.Bold)
        )
        for label in (
            self.label_room, self.label_room_temp, self.label_room_humidity,
            self.label_room_pressure, self.label_out_temp, self.label_today,
            self.label_today_min, self.label_rain, self.label_today_rain,
            self.label_next, self.label_next_min, self.label_next_rain,
            self.label_next_rain_value,
        ):
            label.setFont(QFont("Arial", info_size, QFont.Weight.Bold))
        for label in (
            self.label_solar, self.label_battery, self.label_grid,
            self.label_value_grid,
        ):
            label.setFont(QFont("Arial", power_size, QFont.Weight.Bold))
        for bar in (
            self.solar_power_bar, self.battery_power_bar, self.grid_power_bar,
        ):
            bar.setFont(QFont("Arial", power_size, QFont.Weight.Bold))
            if height <= 420:
                bar.setFixedHeight(48)
            else:
                bar.setFixedHeight(34)
        if height <= 420:
            for label in (
                self.label_out_temp, self.label_today, self.label_today_min,
                self.label_today_rain, self.label_next, self.label_next_min,
                self.label_next_rain, self.label_next_rain_value,
            ):
                label.setMinimumHeight(44)
        else:
            for label in (
                self.label_out_temp, self.label_today, self.label_today_min,
                self.label_today_rain, self.label_next, self.label_next_min,
                self.label_next_rain, self.label_next_rain_value,
            ):
                label.setMinimumHeight(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._layout_ready and not self._configuring_screen:
            self._configure_visibility(self.height())
            self._configure_fonts(self.width(), self.height())

    def _apply_clock_style(self):
        self.setStyleSheet("QMainWindow, QWidget { background-color: white; }")
        yellow = QPalette()
        yellow.setColor(QPalette.ColorRole.WindowText, QColor(240, 240, 26))
        yellow.setColor(QPalette.ColorRole.Text, QColor(240, 240, 26))
        yellow.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0))
        for label in (
            self.label_clock_display, self.label_day_abbrev, self.label_day,
            self.label_month_abbrev, self.label_year, self.text_clock_message,
        ):
            label.setPalette(yellow)
        clock_border = (
            "background-color: black; color: yellow; "
            "border: 3px solid white;"
        )
        for label in (
            self.label_clock_display, self.text_clock_message,
            self.label_day_abbrev, self.label_day, self.label_month_abbrev,
            self.label_year,
        ):
            label.setStyleSheet(clock_border)
        for label in (
            self.label_room, self.label_room_temp, self.label_room_humidity,
            self.label_room_pressure, self.label_out_temp, self.label_today,
            self.label_today_min, self.label_rain, self.label_today_rain,
            self.label_next, self.label_next_min, self.label_next_rain,
            self.label_next_rain_value, self.label_solar, self.label_battery,
            self.label_grid, self.label_value_grid,
        ):
            label.setStyleSheet("background-color: white; color: black;")
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
        solar_percent = max(0, min(100, solar / 10 * 100))
        self.solar_power_bar.set_percentage(
            solar_percent, f"Solar: {solar:.1f}kW {solar_percent:.0f}%"
        )
        self.battery_power_bar.set_percentage(
            soc, f"Battery: {soc}% {battery:+.2f}kW"
        )
        self.grid_power_bar.set_flow(grid, f"Grid: {grid:+.2f}kW")

    def _replace_power_widgets(self):
        self.solar_power_bar = ZeroCenteredPowerBar(
            maximum_kw=10.0, percentage_fill=True, parent=self
        )
        self.battery_power_bar = ZeroCenteredPowerBar(
            percentage_fill=True, bordered=True, parent=self
        )
        self.grid_power_bar = ZeroCenteredPowerBar(parent=self)
        self.battery_flow_bar = ZeroCenteredPowerBar(parent=self)
        self.grid_flow_bar = ZeroCenteredPowerBar(parent=self)
        for widget in (
            self.label_solar, self.progressBar_solar, self.label_battery,
            self.progressBar_battery, self.label_grid, self.label_value_grid,
        ):
            self.horizontalLayout_power.removeWidget(widget)
            widget.hide()
        self.horizontalLayout_power.addWidget(self.solar_power_bar)
        self.horizontalLayout_power.addWidget(self.battery_power_bar)
        self.horizontalLayout_power.addWidget(self.grid_power_bar)
        self.progressBar_battery.hide()
        self.label_value_grid.hide()

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
                self._forecast_date(today), today
            )
        if tomorrow:
            self._set_forecast_row(
                self.label_next, self.label_next_min, self.label_next_rain_value,
                self._forecast_date(tomorrow), tomorrow
            )

    @staticmethod
    def _forecast_date(item):
        timestamp = item.get("utc_timestamp")
        if timestamp:
            try:
                parsed = datetime.datetime.fromisoformat(
                    str(timestamp).replace("Z", "+00:00")
                )
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone()
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                pass

        try:
            day_index = int(item.get("day_index", 0))
        except (TypeError, ValueError):
            return "--"
        return (datetime.datetime.now() + datetime.timedelta(days=day_index)).strftime(
            "%Y-%m-%d"
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
        date_label.setText(f"{title}: ")
        range_label.setText(self._temperature_range(item))
        probability = item.get("rain_probability")
        if probability is None:
            rain_label.setText("--%")
            rain_label.setStyleSheet(
                "background-color: white; color: black; font-weight: bold;"
            )
            return
        probability = max(0, min(100, int(float(probability))))
        rain_label.setText(f"{probability}%")
        red = round(255 * probability / 100)
        green = round(255 * (1 - probability / 100))
        rain_label.setStyleSheet(
            f"background-color: rgb({red}, {green}, 0);"
            " color: black; font-weight: bold;"
        )

    def eventFilter(self, watched, event):
        if event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.TouchBegin,
            QEvent.Type.KeyPress,
        ):
            if self.host_schedule:
                now = datetime.datetime.now()
                if not self.host_schedule.is_scheduled_on(now.time()):
                    self._touch_wake_until = (
                        now + self.host_schedule.touch_on_duration
                    )
                self._wake_display()
            elif self.screen_saver_enabled:
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
        if not (self.screen_saver_enabled or self.host_schedule):
            return
        self.display_is_sleeping = True
        self._idle_timer.stop()
        self._wake_timer.stop()
        self._sleep_overlay.setGeometry(self.rect())
        self._sleep_overlay.raise_()
        self._sleep_overlay.show()
        self._set_display_power(False)

    def _wake_display(self):
        self._set_display_power(True)
        self._sleep_overlay.hide()
        self.display_is_sleeping = False
        self._idle_timer.stop()
        if not self.host_schedule:
            self._wake_timer.start(self.wake_duration_ms)

    def _set_display_power(self, enabled):
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
            except (OSError, subprocess.SubprocessError) as exc:
                LOGGER.warning(
                    "Display power command failed (%s): %s",
                    " ".join(command),
                    exc,
                )

        LOGGER.warning(
            "No working display power command was available; "
            "using the software sleep overlay only"
        )

    def _update_schedule(self):
        if not self.host_schedule:
            return
        now = datetime.datetime.now()
        scheduled_on = self.host_schedule.is_scheduled_on(now.time())
        touch_on = (
            self._touch_wake_until is not None
            and now < self._touch_wake_until
        )
        if scheduled_on or touch_on:
            if self.display_is_sleeping:
                self._wake_display()
        else:
            self._touch_wake_until = None
            if not self.display_is_sleeping:
                self._sleep_display()

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self._idle_timer.stop()
        self._wake_timer.stop()
        self._schedule_timer.stop()
        self._clock_timer.stop()
        self.mqtt_listener.stop()
        if self._cursor_hidden:
            QApplication.restoreOverrideCursor()
            self._cursor_hidden = False
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
        default=None,
        help="Room telemetry topic suffix, e.g. rumpus or bathroom",
    )
    args = parser.parse_args()

    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    app = QApplication(sys.argv)
    hostname = socket.gethostname()
    host_schedule = _load_clock_host_schedule(hostname)
    window = ClockWindow(
        broker=args.broker or _load_broker(),
        screen_saver=args.screen_saver,
        idle_timeout=args.idle_seconds,
        wake_duration=args.wake_seconds,
        location=args.location,
        host_schedule=host_schedule,
    )
    window.configure_screen(args.width, args.height)
    window.force_fullscreen()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
