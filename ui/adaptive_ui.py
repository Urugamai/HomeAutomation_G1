import datetime
import json
import logging
import math
import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QTableWidget,
    QTableWidgetItem, QHeaderView, QSizePolicy,
)
from PyQt6.QtCore import QTimer, QTime, QDate, Qt, QRect, QRectF
from PyQt6.QtGui import QFont, QColor, QPainter, QBrush, QPen, QPolygonF
from PyQt6.QtCore import QPointF

from .hvac_page import HvacConfigurationPage

LOGGER = logging.getLogger(__name__)


class PowerHistoryStore:
    """Persists the current day's house power samples on the NAS."""

    STORAGE_PATH = Path("/mnt/WatsonHome/home_power_history.json")

    def __init__(self, storage_path=None):
        self.storage_path = Path(storage_path or self.STORAGE_PATH)
        self.samples = []
        self._storage_warning_logged = False
        self._load_today()

    def _load_today(self):
        if not self.storage_path.is_file():
            return
        try:
            with self.storage_path.open("r", encoding="utf-8") as history_file:
                payload = json.load(history_file)
            if payload.get("date") != self._today():
                return
            self.samples = [
                (
                    datetime.datetime.fromisoformat(item["timestamp"]),
                    float(item["power_kw"]),
                )
                for item in payload.get("samples", [])
            ]
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            LOGGER.warning("Unable to load power history from %s: %s", self.storage_path, exc)
            self.samples = []

    @staticmethod
    def _today():
        return datetime.date.today().isoformat()

    def add_sample(self, timestamp, power_kw):
        if timestamp.date().isoformat() != self._today():
            self.samples = []
        self.samples.append((timestamp, float(power_kw)))
        self._write()

    def _write(self):
        if not self.storage_path.parent.is_dir():
            if not self._storage_warning_logged:
                LOGGER.warning(
                    "Power history storage is unavailable: %s",
                    self.storage_path.parent,
                )
                self._storage_warning_logged = True
            return

        payload = {
            "date": self._today(),
            "samples": [
                {
                    "timestamp": timestamp.isoformat(timespec="seconds"),
                    "power_kw": power_kw,
                }
                for timestamp, power_kw in self.samples
            ],
        }
        temporary_path = self.storage_path.with_suffix(".tmp")
        try:
            with temporary_path.open("w", encoding="utf-8") as history_file:
                json.dump(payload, history_file, separators=(",", ":"))
                history_file.flush()
                os.fsync(history_file.fileno())
            os.replace(temporary_path, self.storage_path)
        except OSError as exc:
            LOGGER.warning("Unable to save power history to %s: %s", self.storage_path, exc)
            try:
                temporary_path.unlink()
            except OSError:
                pass


class PowerConsumptionChart(QWidget):
    """Paints a midnight-to-midnight house power chart."""

    def __init__(self):
        super().__init__()
        self.samples = []
        self.latest_power_kw = None
        self.setMinimumHeight(150)

    def set_samples(self, samples):
        self.samples = list(samples)
        if self.samples:
            self.latest_power_kw = self.samples[-1][1]
        self.update()

    def set_latest_power(self, power_kw):
        self.latest_power_kw = float(power_kw)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        left = 58
        right = 36
        top = 24
        bottom = 30
        plot = QRect(left, top, max(1, self.width() - left - right),
                     max(1, self.height() - top - bottom))

        painter.setPen(QPen(QColor("#202020"), 1))
        latest_text = (
            f"Latest: {self.latest_power_kw:.2f} kW"
            if self.latest_power_kw is not None
            else "Latest: --"
        )
        painter.drawText(8, 16, f"House power consumption (kW)   {latest_text}")
        painter.drawRect(plot)

        # X-axis time grid lines and labels
        for hour in (0, 6, 12, 18, 24):
            x = plot.left() + plot.width() * hour / 24
            painter.setPen(QPen(QColor("#d8d8d8"), 1))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(QColor("#404040"))
            painter.setFont(QFont("Arial", 8))
            painter.drawText(int(x - 18), self.height() - 8, f"{hour:02d}:00")

        if self.samples:
            values = [value for _, value in self.samples]
            minimum = min(values)
            maximum = max(values)
            raw_min = min(0.0, minimum)
            raw_max = max(0.0, maximum)
            if raw_max == raw_min:
                padding = 1.0
            else:
                padding = max(0.5, (raw_max - raw_min) * 0.1)
            chart_min = raw_min - padding
            chart_max = raw_max + padding
        else:
            chart_min = 0.0
            chart_max = 5.0

        # Calculate Y-axis tick intervals
        range_val = chart_max - chart_min
        if range_val <= 0:
            range_val = 1.0
        raw_step = range_val / 5.0
        magnitude = 10 ** math.floor(math.log10(raw_step)) if raw_step > 0 else 1.0
        norm_step = raw_step / magnitude
        if norm_step < 1.5:
            step = 1.0 * magnitude
        elif norm_step < 3.5:
            step = 2.0 * magnitude
        elif norm_step < 7.5:
            step = 5.0 * magnitude
        else:
            step = 10.0 * magnitude

        # Draw Y-axis scale, horizontal grid, and zero line
        first_tick = math.ceil(chart_min / step) * step
        current_tick = first_tick
        while current_tick <= chart_max + 1e-6:
            y = plot.bottom() - ((current_tick - chart_min) / (chart_max - chart_min) * plot.height())
            if plot.top() <= y <= plot.bottom():
                if abs(current_tick) < 1e-6:
                    # Prominent zero line
                    painter.setPen(QPen(QColor("#606060"), 1.5, Qt.PenStyle.DashLine))
                    painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
                else:
                    # Minor horizontal grid line
                    painter.setPen(QPen(QColor("#eaeaea"), 1, Qt.PenStyle.SolidLine))
                    painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

                # Y-axis tick label
                painter.setPen(QColor("#505050"))
                painter.setFont(QFont("Arial", 8))
                label_text = f"{current_tick:.1f}" if step < 1.0 or abs(current_tick - round(current_tick)) > 0.01 else f"{int(round(current_tick))}"
                painter.drawText(
                    QRectF(0, y - 8, left - 6, 16),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    label_text,
                )
            current_tick += step

        if not self.samples:
            painter.setPen(QColor("#606060"))
            painter.setFont(QFont("Arial", 10))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Waiting for power samples")
            return

        def point_for(timestamp, value):
            seconds = (
                timestamp.hour * 3600
                + timestamp.minute * 60
                + timestamp.second
                + timestamp.microsecond / 1_000_000
            )
            x = plot.left() + plot.width() * seconds / (24 * 3600)
            y = plot.bottom() - (
                (value - chart_min) / (chart_max - chart_min) * plot.height()
            )
            return QPointF(x, y)

        for value, color in ((maximum, QColor("#d62728")), (minimum, QColor("#1f5fbf"))):
            y = point_for(datetime.datetime.combine(
                datetime.date.today(), datetime.time.min
            ), value).y()
            painter.setPen(QPen(color, 1.5, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(color)
            painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            painter.drawText(plot.right() - 72, int(y - 3), f"{value:.2f} kW")

        polyline = QPolygonF([point_for(timestamp, value) for timestamp, value in self.samples])
        painter.setPen(QPen(QColor("#202020"), 2))
        painter.drawPolyline(polyline)

class HighResZeroCenteredBar(QWidget):
    """A custom graphical meter that dynamically paints vector bars relative to a central zero."""

    def __init__(self, range_max_kw=5.0, is_solar=False):
        super().__init__()
        self.range_max = float(range_max_kw)
        self.is_solar = is_solar
        self.current_value = 0.0
        self.setMinimumHeight(24)

    def set_value(self, value: float):
        if self.is_solar:
            self.current_value = max(0.0, min(self.range_max, float(value)))
        else:
            self.current_value = max(-self.range_max, min(self.range_max, float(value)))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        painter.setPen(QPen(QColor(180, 180, 180), 1))
        painter.setBrush(QBrush(QColor(240, 240, 240)))
        painter.drawRoundedRect(0, 0, w, h, 4, 4)

        center_x = w // 2

        if self.is_solar:
            fill_width = int((self.current_value / self.range_max) * w)
            painter.setBrush(QBrush(QColor(40, 167, 69)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(0, 0, fill_width, h)
        else:
            pct = self.current_value / self.range_max
            fill_width = int(abs(pct) * (w / 2))

            if abs(self.current_value) < 0.10:
                painter.setBrush(QBrush(QColor(140, 140, 140)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(center_x - 3, 0, 6, h)
            elif self.current_value > 0:
                painter.setBrush(QBrush(QColor(40, 167, 69)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(center_x, 0, fill_width, h)
            else:
                painter.setBrush(QBrush(QColor(220, 53, 69)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(center_x - fill_width, 0, fill_width, h)

            painter.setPen(QPen(QColor(80, 80, 80), 1, Qt.PenStyle.DashLine))
            painter.drawLine(center_x, 0, center_x, h)


class AdaptiveSocBar(QWidget):
    """Vertical battery state of charge bar with embedded label and percentage."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.soc_val = None
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFixedWidth(56)
        self.setMinimumHeight(100)

    def set_value(self, value: float):
        self.soc_val = max(0.0, min(100.0, float(value)))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        painter.setPen(QPen(QColor(180, 180, 180), 1))
        painter.setBrush(QBrush(QColor(240, 240, 240)))
        painter.drawRoundedRect(0, 0, w, h, 4, 4)

        if self.soc_val is not None:
            fill_height = int((self.soc_val / 100.0) * h)
            if fill_height > 0:
                painter.setPen(Qt.PenStyle.NoPen)
                fill_color = QColor(40, 167, 69) if self.soc_val > 20 else QColor(220, 53, 69)
                painter.setBrush(QBrush(fill_color))
                painter.drawRoundedRect(0, h - fill_height, w, fill_height, 4, 4)

        painter.setPen(QPen(QColor(120, 120, 120), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(0, 0, w, h, 4, 4)

        painter.setPen(QColor(0, 0, 0))
        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        val_str = f"{self.soc_val:.1f}%" if self.soc_val is not None else "--%"
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"SOC\n{val_str}")


class AdaptiveFlowWidget(QWidget):
    """Wrapper component coupling text status titles to custom vector graphics."""

    def __init__(self, label_text: str, range_max_kw=5.0, is_solar=False):
        super().__init__()
        self.base_title = label_text
        self.is_solar = is_solar
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        self.lbl = QLabel(f"{self.base_title}: -- kW")
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(self.lbl)

        self.meter = HighResZeroCenteredBar(range_max_kw=range_max_kw, is_solar=is_solar)
        layout.addWidget(self.meter)

    def update_flow_value(self, value: float, override_title=None):
        self.meter.set_value(value)
        title = override_title if override_title else self.base_title
        if self.is_solar:
            self.lbl.setText(f"{title}: {value:.1f} kW")
        else:
            self.lbl.setText(f"{title}: {value:.2f} kW")


class EnvironmentSourcesPage(QWidget):
    """Table of the latest telemetry received from each environment source."""

    COLUMNS = (
        "Source", "Hostname", "Temperature", "Humidity", "Pressure",
        "Light", "Wind", "Rain", "Updated",
    )

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("Environment Sources")
        title.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        layout.addWidget(title)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

    @staticmethod
    def _value(source, *keys, default="--"):
        for key in keys:
            value = source.get(key)
            if value is not None:
                return value
        return default

    @classmethod
    def _number(cls, source, *keys, suffix=""):
        value = cls._value(source, *keys, default=None)
        if value is None:
            return "--"
        try:
            return f"{float(value):.1f}{suffix}"
        except (TypeError, ValueError):
            return str(value)

    @classmethod
    def _source_row(cls, source_key, source):
        is_ecowitt = source_key == "Ecowitt"
        light_suffix = " W/m²" if is_ecowitt else " lx"
        return (
            "Ecowitt" if is_ecowitt else source_key,
            source.get("hostname") or source.get("device_name") or "--",
            cls._number(source, "temperature", "outside_temp", "outdoor_temp", suffix=" °C"),
            cls._number(source, "humidity", "outside_humidity", suffix=" %"),
            cls._number(source, "pressure", suffix=" hPa"),
            cls._number(
                source,
                "solar_radiation" if is_ecowitt else "light_lux",
                "outside_lux",
                suffix=light_suffix,
            ),
            cls._number(source, "wind_speed", "wind_speed_kmh", suffix=" km/h"),
            cls._number(source, "rain_rate", suffix=" mm/h"),
            cls._number(source, "timestamp"),
        )

    def refresh_sources(self, sources):
        ordered_sources = sorted(
            sources.items(),
            key=lambda item: (item[0] != "Ecowitt", item[0].lower()),
        )
        self.table.setRowCount(len(ordered_sources))
        for row, (source_key, source) in enumerate(ordered_sources):
            for column, value in enumerate(self._source_row(source_key, source)):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))


class AdaptiveDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.root_layout = QHBoxLayout(self)
        self.root_layout.setContentsMargins(10, 10, 10, 10)
        self.root_layout.setSpacing(10)

        # Full-height vertical Battery SOC bar on the left
        self.soc_bar = AdaptiveSocBar()
        self.root_layout.addWidget(self.soc_bar)

        # Right-side vertical stack for clock, weather, energy, chart
        self.content_widget = QWidget()
        self.main_layout = QVBoxLayout(self.content_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(8)
        self.root_layout.addWidget(self.content_widget, 1)

        # 1. Digital Clock Panel
        self.time_lbl = QLabel("Initializing Clock...")
        self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.time_lbl)

        # 2. Main Ambient Climates & Light Readouts Panel
        self.temp_lbl = QLabel("Waiting for live telemetry...")
        self.temp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.temp_lbl)

        # 3. Weather Forecast Matrix
        self.forecast_container = QWidget()
        self.forecast_layout = QHBoxLayout(self.forecast_container)
        self.forecast_layout.setContentsMargins(0, 4, 0, 4)
        self.forecast_layout.setSpacing(15)

        self.today_forecast_lbl = QLabel("Today: Loading...")
        self.today_forecast_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.today_forecast_lbl.setStyleSheet("background-color: #f8f9fa; border-radius: 4px; padding: 4px;")

        self.tomorrow_forecast_lbl = QLabel("Tomorrow: Loading...")
        self.tomorrow_forecast_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tomorrow_forecast_lbl.setStyleSheet("background-color: #f8f9fa; border-radius: 4px; padding: 4px;")

        self.forecast_layout.addWidget(self.today_forecast_lbl)
        self.forecast_layout.addWidget(self.tomorrow_forecast_lbl)
        self.main_layout.addWidget(self.forecast_container)

        # 4. Energy Metrics Grid Panel
        self.energy_container = QWidget()
        energy_layout = QHBoxLayout(self.energy_container)
        energy_layout.setContentsMargins(0, 0, 0, 0)
        energy_layout.setSpacing(10)

        self.solar_widget = AdaptiveFlowWidget("Solar Gen", range_max_kw=10.0, is_solar=True)
        self.battery_widget = AdaptiveFlowWidget("Battery Flow", range_max_kw=5.0)
        self.grid_widget = AdaptiveFlowWidget("Grid Flow", range_max_kw=5.0)

        energy_layout.addWidget(self.solar_widget)
        energy_layout.addWidget(self.battery_widget)
        energy_layout.addWidget(self.grid_widget)
        self.main_layout.addWidget(self.energy_container)

        self.power_history = PowerHistoryStore()
        self.power_chart = PowerConsumptionChart()
        self.main_layout.addWidget(self.power_chart, 1)
        self._latest_power_sample = None
        self.power_sample_timer = QTimer(self)
        self.power_sample_timer.timeout.connect(self._record_power_sample)
        self.power_sample_timer.start(15_000)
        self.power_chart.set_samples(self.power_history.samples)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_time)
        self.timer.start(1000)

        self.current_profile = "UNKNOWN"
        self.hvac_config_tab = None

    def apply_hardware_profile(self, width: int, height: int, parent_tab_widget=None):
        aspect_ratio = width / height
        if aspect_ratio >= 2.5 or height < 250:
            self.current_profile = "BANNER_CLOCK"
            self.temp_lbl.hide()
            self.forecast_container.hide()
            self.energy_container.hide()
            self.power_chart.hide()
            self.soc_bar.hide()
            self.time_lbl.setFont(QFont("Monospace", 22, QFont.Weight.Bold))
        elif height < 500:
            self.current_profile = "COMPACT_DESK"
            self.temp_lbl.show()
            self.forecast_container.show()
            self.energy_container.hide()
            self.power_chart.hide()
            self.soc_bar.hide()
            self.time_lbl.setFont(QFont("Monospace", 28, QFont.Weight.Bold))
            self.temp_lbl.setFont(QFont("Arial", 11, QFont.Weight.Medium))
            self._mount_hvac_view(parent_tab_widget)
        else:
            self.current_profile = "FULL_COMMAND_HUB"
            self.temp_lbl.show()
            self.forecast_container.show()
            self.energy_container.show()
            self.power_chart.show()
            self.soc_bar.show()
            self.time_lbl.setFont(QFont("Monospace", 36, QFont.Weight.Bold))
            self.temp_lbl.setFont(QFont("Arial", 13, QFont.Weight.Medium))
            self._mount_hvac_view(parent_tab_widget)

    def _mount_hvac_view(self, parent_tab_widget):
        if parent_tab_widget and self.hvac_config_tab is None:
            self.hvac_config_tab = HvacConfigurationPage()
            self.hvac_config_tab.update_display_metrics()
            parent_tab_widget.addTab(self.hvac_config_tab, "Climate Settings")

    def _refresh_time(self):
        now = QTime.currentTime().toString("hh:mm:ss")
        date = QDate.currentDate().toString("ddd dd MMM yyyy")
        self.time_lbl.setText(f"{now}   {date}" if self.current_profile == "BANNER_CLOCK" else f"{now}\n{date}")

    def refresh_telemetry_ui(self, data: dict):
        try:
            self._latest_power_sample = (
                float(data.get("solar_power", 0.0))
                - float(data.get("battery_flow", 0.0))
                + float(data.get("grid_flow", 0.0))
            )
            self.power_chart.set_latest_power(self._latest_power_sample)
        except (TypeError, ValueError):
            self._latest_power_sample = None

        if self.temp_lbl.isVisible():
            # FIXED: Render high-resolution Lux light parameters directly alongside room temperatures
            l_temp = data.get("living_temp", 0.0)
            l_solar = data.get("living_lux", 0.0)
            o_temp = data.get("outside_temp", 0.0)
            o_solar = data.get("solar_radiation", 0.0)
            o_humidity = data.get("outside_humidity", 0.0)
            wind_speed = data.get("wind_speed", 0.0)
            wind_gust = data.get("wind_gust", 0.0)
            wind_direction = data.get("wind_direction", 0.0)
            rain_today = data.get("rain_today", 0.0)
            rain_rate = data.get("rain_rate", 0.0)
            self.temp_lbl.setText(
                f"Living: {l_temp:.1f}°C ({l_solar:.1f} W/m²)  |  "
                f"Outside: {o_temp:.1f}°C, {o_humidity:.0f}% RH "
                f"({o_solar:.1f} W/m²)<br>"
                f"Wind: {wind_speed:.1f} km/h (gust {wind_gust:.1f}) "
                f"from {wind_direction:.0f}°  |  "
                f"Rain: {rain_today:.1f} mm today ({rain_rate:.1f} mm/h)"
            )

        if self.energy_container.isVisible():
            soc_val = data.get("battery_soc", 0.0)
            self.soc_bar.set_value(soc_val)

            solar_kw = float(data.get("solar_power", 0.0))
            battery_kw = float(data.get("battery_flow", 0.0))
            grid_kw = float(data.get("grid_flow", 0.0))
            solar_kwh = float(data.get("solar_kwh_today", 0.0))

            self.solar_widget.update_flow_value(solar_kw, override_title=f"Solar ({solar_kwh:.2f} kWh)")
            self.battery_widget.update_flow_value(battery_kw)
            self.grid_widget.update_flow_value(grid_kw)

        if self.forecast_container.isVisible() and "forecast_set" in data:
            self._update_forecast_labels(data["forecast_set"])

    def _record_power_sample(self):
        if self._latest_power_sample is None:
            return
        self.power_history.add_sample(
            datetime.datetime.now(),
            self._latest_power_sample,
        )
        self.power_chart.set_samples(self.power_history.samples)

    def _update_forecast_labels(self, forecast_list):
        today_data = next((x for x in forecast_list if x.get("day_index") == 0), None)
        tomorrow_data = next((x for x in forecast_list if x.get("day_index") == 1), None)

        if today_data:
            t_max = today_data.get("expected_max")
            t_min = today_data.get("expected_min")
            if t_max is None and t_min is None:
                temp_str = "--°C"
            elif t_min is None:
                temp_str = f"{t_max:.1f}°C"
            elif t_max is None:
                temp_str = f"{t_min:.1f}°C"
            else:
                temp_str = f"{t_min:.1f}°C → {t_max:.1f}°C"
            rain_str = self._format_rain_probability(today_data)
            self.today_forecast_lbl.setText(
                f"<b>{self._forecast_date(today_data)}</b><br>"
                f"<font color='#17a2b8'>{temp_str}</font>"
                f"<br><font color='#007bff'>{rain_str}</font>"
                f"<br><i>{today_data.get('summary', '')}</i>"
            )

        if tomorrow_data:
            tm_max = tomorrow_data.get("expected_max")
            tm_min = tomorrow_data.get("expected_min")
            if tm_max is None and tm_min is None:
                temp_str = "--°C"
            elif tm_min is None:
                temp_str = f"{tm_max:.1f}°C"
            elif tm_max is None:
                temp_str = f"{tm_min:.1f}°C"
            else:
                temp_str = f"{tm_min:.1f}°C → {tm_max:.1f}°C"
            rain_str = self._format_rain_probability(tomorrow_data)
            self.tomorrow_forecast_lbl.setText(
                f"<b>{self._forecast_date(tomorrow_data)}</b><br>"
                f"<font color='#007aff'>{temp_str}</font>"
                f"<br><font color='#007bff'>{rain_str}</font>"
                f"<br><i>{tomorrow_data.get('summary', '')}</i>"
            )

    @staticmethod
    def _forecast_date(forecast_data):
        timestamp = forecast_data.get("utc_timestamp")
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
            day_index = int(forecast_data.get("day_index", 0))
        except (TypeError, ValueError):
            return "--"
        return (datetime.datetime.now() + datetime.timedelta(days=day_index)).strftime(
            "%Y-%m-%d"
        )

    @staticmethod
    def _format_rain_probability(forecast_data):
        probability = forecast_data.get("rain_probability")
        if probability is None:
            return "Rain: --%"
        try:
            return f"Rain: {float(probability):.0f}%"
        except (TypeError, ValueError):
            return "Rain: --%"


AdaptiveFlowWidget.update_widget_draw_palette = AdaptiveFlowWidget.update_flow_value
