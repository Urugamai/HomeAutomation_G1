from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from PyQt6.QtCore import QTimer, QTime, QDate, Qt
from PyQt6.QtGui import QFont, QColor, QPalette
from hvac_page import HvacConfigurationPage


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

        self.time_lbl = QLabel("Initializing...")
        self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.time_lbl)

        self.temp_lbl = QLabel("Waiting for data...")
        self.temp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.temp_lbl)

        self.energy_container = QWidget()
        energy_layout = QHBoxLayout(self.energy_container)

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
            self.energy_container.hide()
            self.time_lbl.setFont(QFont("Monospace", 24, QFont.Weight.Bold))
            if parent_tab_widget and parent_tab_widget.count() > 1:
                parent_tab_widget.removeTab(1)
        elif height < 500:
            self.current_profile = "COMPACT_DESK"
            self.temp_lbl.show()
            self.energy_container.hide()
            self.time_lbl.setFont(QFont("Monospace", 32, QFont.Weight.Bold))
            self.temp_lbl.setFont(QFont("Arial", 12))
            self._mount_hvac_view(parent_tab_widget)
        else:
            self.current_profile = "FULL_COMMAND_HUB"
            self.temp_lbl.show()
            self.energy_container.show()
            self.time_lbl.setFont(QFont("Monospace", 42, QFont.Weight.Bold))
            self.temp_lbl.setFont(QFont("Arial", 14))
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
            self.temp_lbl.setText(f"Inside: {data['inside_temp']}°C  |  Outside: {data['outside_temp']}°C")
        if self.energy_container.isVisible():
            self.soc_bar.setValue(data['battery_soc'])
            self.battery_widget.update_flow_value(data['battery_flow'])
            self.grid_widget.update_flow_value(data['grid_flow'])
