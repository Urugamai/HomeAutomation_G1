from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QFrame
from PyQt6.QtCore import QTimer, QTime, QDate, Qt
from PyQt6.QtGui import QFont, QColor, QPalette

from .hvac_page import HvacConfigurationPage


class AdaptiveFlowWidget(QWidget):
    def __init__(self, label_text: str):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.lbl = QLabel(label_text)
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(self.lbl)

        self.bar = QProgressBar()
        self.bar.setRange(-5000, 5000)
        self.bar.setValue(0)
        self.bar.setFormat("%v W")
        layout.addWidget(self.bar)

    def update_flow_value(self, value: int):
        self.bar.setValue(value)
        palette = self.bar.palette()
        if value < -100:
            palette.setColor(QPalette.ColorRole.Highlight, QColor(220, 50, 50))
        elif value > 100:
            palette.setColor(QPalette.ColorRole.Highlight, QColor(50, 200, 50))
        else:
            palette.setColor(QPalette.ColorRole.Highlight, QColor(130, 130, 130))
        self.bar.setPalette(palette)


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

        # 2. Inside / Outside Real-time Temperatures
        self.temp_lbl = QLabel("Waiting for live telemetry...")
        self.temp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.temp_lbl)

        # 3. Dynamic Multi-Day Weather Forecast Matrix (Added Feature)
        self.forecast_container = QWidget()
        self.forecast_layout = QHBoxLayout(self.forecast_container)
        self.forecast_layout.setContentsMargins(0, 4, 0, 4)
        self.forecast_layout.setSpacing(15)

        self.today_forecast_lbl = QLabel("Today: Loading forecast...")
        self.today_forecast_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.today_forecast_lbl.setStyleSheet("background-color: #f8f9fa; border-radius: 4px; padding: 4px;")

        self.tomorrow_forecast_lbl = QLabel("Tomorrow: Loading forecast...")
        self.tomorrow_forecast_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tomorrow_forecast_lbl.setStyleSheet("background-color: #f8f9fa; border-radius: 4px; padding: 4px;")

        self.forecast_layout.addWidget(self.today_forecast_lbl)
        self.forecast_layout.addWidget(self.tomorrow_forecast_lbl)
        self.main_layout.addWidget(self.forecast_container)

        # 4. Energy Ingestion & Flow Meters Panel
        self.energy_container = QWidget()
        energy_layout = QHBoxLayout(self.energy_container)
        energy_layout.setContentsMargins(0, 0, 0, 0)

        self.soc_bar = QProgressBar()
        self.soc_bar.setOrientation(Qt.Orientation.Vertical)
        self.soc_bar.setRange(0, 100)

        self.battery_widget = AdaptiveFlowWidget("Battery Flow")
        self.grid_widget = AdaptiveFlowWidget("Grid Flow")

        energy_layout.addWidget(QLabel("SOC:"))
        energy_layout.addWidget(self.soc_bar)
        energy_layout.addWidget(self.battery_widget)
        energy_layout.addWidget(self.grid_widget)
        self.main_layout.addWidget(self.energy_container)

        # Start master background system time loops
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_time)
        self.timer.start(1000)

        self.current_profile = "UNKNOWN"
        self.hvac_config_tab = None

    def apply_hardware_profile(self, width: int, height: int, parent_tab_widget=None):
        aspect_ratio = width / height

        # Profile A: Narrow 200x70mm Shelf Clocks - Aggressive minimization rules
        if aspect_ratio >= 2.5 or height < 250:
            self.current_profile = "BANNER_CLOCK"
            self.temp_lbl.hide()
            self.forecast_container.hide()  # Strip heavy forecast arrays entirely
            self.energy_container.hide()
            self.time_lbl.setFont(QFont("Monospace", 22, QFont.Weight.Bold))
            if parent_tab_widget and parent_tab_widget.count() > 1:
                parent_tab_widget.removeTab(1)

        # Profile B: Compact 5" Desk Modules
        elif height < 500:
            self.current_profile = "COMPACT_DESK"
            self.temp_lbl.show()
            self.forecast_container.show()  # Display minimal text forecast frames
            self.energy_container.hide()

            self.time_lbl.setFont(QFont("Monospace", 28, QFont.Weight.Bold))
            self.temp_lbl.setFont(QFont("Arial", 11, QFont.Weight.Medium))
            self.today_forecast_lbl.setFont(QFont("Arial", 10))
            self.tomorrow_forecast_lbl.setFont(QFont("Arial", 10))
            self._mount_hvac_view(parent_tab_widget)

        # Profile C: Full 10" Automation Central Hubs
        else:
            self.current_profile = "FULL_COMMAND_HUB"
            self.temp_lbl.show()
            self.forecast_container.show()
            self.energy_container.show()

            self.time_lbl.setFont(QFont("Monospace", 36, QFont.Weight.Bold))
            self.temp_lbl.setFont(QFont("Arial", 13, QFont.Weight.Medium))
            self.today_forecast_lbl.setFont(QFont("Arial", 11))
            self.tomorrow_forecast_lbl.setFont(QFont("Arial", 11))
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
        """Processes incoming unified telemetry dictionary updates."""
        if self.temp_lbl.isVisible():
            self.temp_lbl.setText(f"Inside: {data['inside_temp']}°C  |  Outside: {data['outside_temp']}°C")

        if self.energy_container.isVisible():
            self.soc_bar.setValue(data['battery_soc'])
            self.battery_widget.update_flow_value(data['battery_flow'])
            self.grid_widget.update_flow_value(data['grid_flow'])

        # Process and render live BOM multi-day arrays if present
        if self.forecast_container.isVisible() and "forecast_set" in data:
            self._update_forecast_labels(data["forecast_set"])

    def _update_forecast_labels(self, forecast_list):
        """Helper matrix that safely reformats text blocks for the display lines."""
        today_data = None
        tomorrow_data = None

        for item in forecast_list:
            if item.get("day_index") == 0:
                today_data = item
            elif item.get("day_index") == 1:
                tomorrow_data = item

        # Reformat Today's visual widget cards
        if today_data:
            t_max = today_data.get("expected_max")
            t_min = today_data.get("expected_min")
            summary = today_data.get("summary", "")

            # Format ranges cleanly matching active weather constraints
            temp_str = f"{t_max}°C" if t_min is None else f"{t_min}°C → {t_max}°C"
            self.today_forecast_lbl.setText(f"<b>Today</b><br><font color='#17a2b8'>{temp_str}</font><br><i>{summary}</i>")

        # Reformat Tomorrow's visual widget cards
        if tomorrow_data:
            tm_max = tomorrow_data.get("expected_max")
            tm_min = tomorrow_data.get("expected_min")
            tm_summary = tomorrow_data.get("summary", "")

            temp_str = f"{tm_max}°C" if tm_min is None else f"{tm_min}°C → {tm_max}°C"
            self.tomorrow_forecast_lbl.setText(f"<b>Tomorrow</b><br><font color='#007aff'>{temp_str}</font><br><i>{tm_summary}</i>")
