from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import QTimer, QTime, QDate, Qt, QRect
from PyQt6.QtGui import QFont, QColor, QPainter, QBrush, QPen

from .hvac_page import HvacConfigurationPage


class HighResZeroCenteredBar(QWidget):
    """
    A custom graphical meter that dynamically paints vector bars relative to a central zero.
    - Positive values grow RIGHT (Green)
    - Negative values grow LEFT (Red)
    - Features a customizable deadband buffer zone
    """

    def __init__(self, range_max_kw=5.0, is_solar=False):
        super().__init__()
        self.range_max = float(range_max_kw)
        self.is_solar = is_solar
        self.current_value = 0.0

        # Enforce an explicit vertical footprint matching touchscreen layout rows
        self.setMinimumHeight(24)

    def set_value(self, value: float):
        if self.is_solar:
            self.current_value = max(0.0, min(self.range_max, float(value)))
        else:
            self.current_value = max(-self.range_max, min(self.range_max, float(value)))
        self.update()  # Triggers an immediate native repaint cycle

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Draw Background Track Frame
        w = self.width()
        h = self.height()
        painter.setPen(QPen(QColor(180, 180, 180), 1))
        painter.setBrush(QBrush(QColor(240, 240, 240)))
        painter.drawRoundedRect(0, 0, w, h, 4, 4)

        # 2. Calculate Vector Fill Widths
        center_x = w // 2

        if self.is_solar:
            # Solar only flows positive: Fill from absolute left (0) to right (max)
            fill_width = int((self.current_value / self.range_max) * w)
            painter.setBrush(QBrush(QColor(40, 167, 69)))  # Solid Green
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(0, 0, fill_width, h)
        else:
            # Bidirectional Flow Logic: Calculate scaling relative to the central origin
            pct = self.current_value / self.range_max
            fill_width = int(abs(pct) * (w / 2))

            if abs(self.current_value) < 0.10:
                # Deadband buffer zone: Keep bar centered and neutral grey
                painter.setBrush(QBrush(QColor(140, 140, 140)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(center_x - 3, 0, 6, h)
            elif self.current_value > 0:
                # Positive Power: Grow RIGHT (Green)
                painter.setBrush(QBrush(QColor(40, 167, 69)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(center_x, 0, fill_width, h)
            else:
                # Negative Power: Grow LEFT backwards from center (Red)
                painter.setBrush(QBrush(QColor(220, 53, 69)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(center_x - fill_width, 0, fill_width, h)

            # 3. Draw a structural center indicator line pin marker
            painter.setPen(QPen(QColor(80, 80, 80), 1, Qt.PenStyle.DashLine))
            painter.drawLine(center_x, 0, center_x, h)


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

        # Deploy our new custom canvas rendering engine
        self.meter = HighResZeroCenteredBar(range_max_kw=range_max_kw, is_solar=is_solar)
        layout.addWidget(self.meter)

    def update_flow_value(self, value: float, override_title=None):
        self.meter.set_value(value)
        title = override_title if override_title else self.base_title

        if self.is_solar:
            self.lbl.setText(f"{title}: {value:.1f} kW")
        else:
            self.lbl.setText(f"{title}: {value:.2f} kW")


class AdaptiveDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(8)

        # 1. Digital Clock Panel
        self.time_lbl = QLabel("Initializing Clock...")
        self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.time_lbl)

        # 2. Real-time Climates
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

        from PyQt6.QtWidgets import QProgressBar as QB
        self.soc_bar = QB()
        self.soc_bar.setOrientation(Qt.Orientation.Vertical)
        self.soc_bar.setRange(0, 100)

        # Instantiate widgets passing true operational kW peak limits
        self.solar_widget = AdaptiveFlowWidget("Solar Gen", range_max_kw=10.0, is_solar=True)
        self.battery_widget = AdaptiveFlowWidget("Battery Flow", range_max_kw=5.0)
        self.grid_widget = AdaptiveFlowWidget("Grid Flow", range_max_kw=5.0)

        energy_layout.addWidget(QLabel("SOC:"))
        energy_layout.addWidget(self.soc_bar)
        energy_layout.addWidget(self.solar_widget)
        energy_layout.addWidget(self.battery_widget)
        energy_layout.addWidget(self.grid_widget)
        self.main_layout.addWidget(self.energy_container)

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
            self.time_lbl.setFont(QFont("Monospace", 22, QFont.Weight.Bold))
            if parent_tab_widget and parent_tab_widget.count() > 1:
                parent_tab_widget.removeTab(1)
        elif height < 500:
            self.current_profile = "COMPACT_DESK"
            self.temp_lbl.show()
            self.forecast_container.show()
            self.energy_container.hide()

            self.time_lbl.setFont(QFont("Monospace", 28, QFont.Weight.Bold))
            self.temp_lbl.setFont(QFont("Arial", 11, QFont.Weight.Medium))
            self._mount_hvac_view(parent_tab_widget)
        else:
            self.current_profile = "FULL_COMMAND_HUB"
            self.temp_lbl.show()
            self.forecast_container.show()
            self.energy_container.show()

            self.time_lbl.setFont(QFont("Monospace", 36, QFont.Weight.Bold))
            self.temp_lbl.setFont(QFont("Arial", 13, QFont.Weight.Medium))
            self._mount_hvac_view(parent_tab_widget)

    def _mount_hvac_view(self, parent_tab_widget):
        if parent_tab_widget and parent_tab_widget.count() == 1:
            self.hvac_config_tab = HvacConfigurationPage()
            self.hvac_config_tab.update_display_metrics()
            parent_tab_widget.addTab(self.hvac_config_tab, "Climate Settings")

    def _refresh_time(self):
        now = QTime.currentTime().toString("hh:mm:ss")
        date = QDate.currentDate().toString("ddd dd MMM yyyy")
        self.time_lbl.setText(f"{now}   {date}" if self.current_profile == "BANNER_CLOCK" else f"{now}\n{date}")

    def refresh_telemetry_ui(self, data: dict):
        if self.temp_lbl.isVisible():
            self.temp_lbl.setText(f"Inside: {data['inside_temp']:.1f}°C  |  Outside: {data['outside_temp']:.1f}°C")

        if self.energy_container.isVisible():
            soc_val = data.get("battery_soc", 0.0)
            self.soc_bar.setValue(int(soc_val))

            solar_kw = float(data.get("solar_power", 0.0))
            battery_kw = float(data.get("battery_flow", 0.0))
            grid_kw = float(data.get("grid_flow", 0.0))
            solar_kwh = float(data.get("solar_kwh_today", 0.0))

            self.solar_widget.update_flow_value(solar_kw, override_title=f"Solar ({solar_kwh:.2f} kWh)")
            self.battery_widget.update_flow_value(battery_kw)
            self.grid_widget.update_flow_value(grid_kw)

        if self.forecast_container.isVisible() and "forecast_set" in data:
            self._update_forecast_labels(data["forecast_set"])

    def _update_forecast_labels(self, forecast_list):
        today_data = next((x for x in forecast_list if x.get("day_index") == 0), None)
        tomorrow_data = next((x for x in forecast_list if x.get("day_index") == 1), None)

        if today_data:
            t_max = today_data.get("expected_max")
            t_min = today_data.get("expected_min")
            temp_str = f"{t_max:.1f}°C" if t_min is None else f"{t_min:.1f}°C → {t_max:.1f}°C"
            self.today_forecast_lbl.setText(f"<b>Today</b><br><font color='#17a2b8'>{temp_str}</font><br><i>{today_data.get('summary', '')}</i>")

        if tomorrow_data:
            tm_max = tomorrow_data.get("expected_max")
            tm_min = tomorrow_data.get("expected_min")
            temp_str = f"{tm_max:.1f}°C" if tm_min is None else f"{tm_min:.1f}°C → {tm_max:.1f}°C"
            self.tomorrow_forecast_lbl.setText(f"<b>Tomorrow</b><br><font color='#007aff'>{temp_str}</font><br><i>{tomorrow_data.get('summary', '')}</i>")


AdaptiveFlowWidget.update_widget_draw_palette = AdaptiveFlowWidget.update_flow_value
