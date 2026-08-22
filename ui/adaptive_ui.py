from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from PyQt6.QtCore import QTimer, QTime, QDate, Qt
from PyQt6.QtGui import QFont, QColor, QPalette
from ui.hvac_page import HvacConfigurationPage


class AdaptiveFlowWidget(QWidget):
    """Renders a balanced left-right progress flow bar with color indicators."""

    def __init__(self, label_text: str):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.lbl = QLabel(label_text)
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(self.lbl)

        self.bar = QProgressBar()
        self.bar.setRange(-5000, 5000)  # Balanced watt limits around zero
        self.bar.setValue(0)
        self.bar.setFormat("%v W")
        layout.addWidget(self.bar)

    def update_flow_value(self, value: int):
        self.bar.setValue(value)
        palette = self.bar.palette()

        # Color states based on power flow (with a 100W deadband buffer around zero)
        if value < -100:  # Draining / Exporting
            palette.setColor(QPalette.ColorRole.Highlight, QColor(220, 50, 50))
        elif value > 100:  # Charging / Importing
            palette.setColor(QPalette.ColorRole.Highlight, QColor(50, 200, 50))
        else:  # Idle Deadband
            palette.setColor(QPalette.ColorRole.Highlight, QColor(130, 130, 130))
        self.bar.setPalette(palette)


class AdaptiveDashboard(QWidget):
    """Multi-profile rendering engine tailored to screen real estate rules."""

    def __init__(self):
        super().__init__()
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)

        self.hvac_config_tab = None

        # Component 1: System Digital Clock (Always visible)
        self.time_lbl = QLabel("Initializing Clock...")
        self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.time_lbl)

        # Component 2: Local & Remote Telemetry Labels
        self.temp_lbl = QLabel("Waiting for live telemetry...")
        self.temp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.temp_lbl)

        # Component 3: Complete Power Grid Matrix
        self.energy_container = QWidget()
        energy_layout = QHBoxLayout(self.energy_container)
        energy_layout.setContentsMargins(0, 5, 0, 0)

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

        # Clock updates (driven by a local precise hardware tick)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_time_display)
        self.timer.start(1000)

        self.current_profile = "UNKNOWN"

    def apply_hardware_profile(self, width: int, height: int):
        """Analyzes screen geometry to selectively hide or show elements."""
        aspect_ratio = width / height

        # Profile A: Ultra-wide Shelf Clock Banner Format (e.g., 200mm x 70mm, aspect > 2.5)
        if aspect_ratio >= 2.5 or height < 250:
            self.current_profile = "BANNER_CLOCK"
            self.temp_lbl.hide()
            self.energy_container.hide()
            self.time_lbl.setFont(QFont("Monospace", 24, QFont.Weight.Bold))
            self.main_layout.setContentsMargins(5, 2, 5, 2)

        # Profile B: Compact Desk Panels (e.g., 5-inch 800x480 screen profiles)
        elif height < 500 and aspect_ratio < 2.5:
            self.current_profile = "COMPACT_DESK"
            self.temp_lbl.show()
            self.energy_container.hide()
            self.time_lbl.setFont(QFont("Monospace", 32, QFont.Weight.Bold))
            self.temp_lbl.setFont(QFont("Arial", 12))

        # Profile C: Full Command Interfaces (e.g., 10-inch standard wall screens)
        else:
            self.current_profile = "FULL_COMMAND_HUB"
            self.temp_lbl.show()
            self.energy_container.show()
            self.time_lbl.setFont(QFont("Monospace", 42, QFont.Weight.Bold))
            self.temp_lbl.setFont(QFont("Arial", 14))

        print(f"[UI DETECT] Layout Resolution: {width}x{height} -> Initialized Profile: {self.current_profile}")

    def _refresh_time_display(self):
        now = QTime.currentTime().toString("hh:mm:ss")
        date = QDate.currentDate().toString("ddd dd MMM yyyy")

        if self.current_profile == "BANNER_CLOCK":
            self.time_lbl.setText(f"{now}   {date}")
        else:
            self.time_lbl.setText(f"{now}\n{date}")

    def refresh_telemetry_ui(self, data: dict):
        """Processes live, normalized updates received from the MQTT engine."""
        if self.temp_lbl.isVisible():
            self.temp_lbl.setText(f"Inside: {data['inside_temp']}°C  |  Outside: {data['outside_temp']}°C")
        if self.energy_container.isVisible():
            self.soc_bar.setValue(data['battery_soc'])
            self.battery_widget.update_flow_value(data['battery_flow'])
            self.grid_widget.update_flow_value(data['grid_flow'])


def apply_hardware_profile(self, width: int, height: int, parent_tab_widget=None):
    """
    Analyzes screen dimensions to strip out crowded elements.
    Dynamically hooks or cleanly completely unmounts the HVAC control panel view.
    """
    aspect_ratio = width / height

    # Profile 1: Banner Clocks (200x70mm) - Strict minimalist mode
    if aspect_ratio >= 2.5 or height < 250:
        self.current_profile = "BANNER_CLOCK"
        self.temp_lbl.hide()
        self.energy_container.hide()
        self.time_lbl.setFont(QFont("Monospace", 24, QFont.Weight.Bold))
        self.main_layout.setContentsMargins(5, 2, 5, 2)

        # Cleanly strip configuration submenus if mounted on macro strips
        if parent_tab_widget and parent_tab_widget.count() > 1:
            parent_tab_widget.removeTab(1)

    # Profile 2: Medium/Compact Screens (5-inch Desk Panels)
    elif height < 500 and aspect_ratio < 2.5:
        self.current_profile = "COMPACT_DESK"
        self.temp_lbl.show()
        self.energy_container.hide()
        self.time_lbl.setFont(QFont("Monospace", 32, QFont.Weight.Bold))
        self.temp_lbl.setFont(QFont("Arial", 12))

        self._mount_hvac_view_safely(parent_tab_widget)

    # Profile 3: Full Command Terminals (10-inch Hubs)
    else:
        self.current_profile = "FULL_COMMAND_HUB"
        self.temp_lbl.show()
        self.energy_container.show()
        self.time_lbl.setFont(QFont("Monospace", 42, QFont.Weight.Bold))
        self.temp_lbl.setFont(QFont("Arial", 14))

        self._mount_hvac_view_safely(parent_tab_widget)


def _mount_hvac_view_safely(self, parent_tab_widget):
    """Safely inserts the HVAC control screen into tabbed environments without causing duplicates."""
    if parent_tab_widget and parent_tab_widget.count() == 1:
        self.hvac_config_tab = HvacConfigurationPage()
        self.hvac_config_tab.update_display_metrics()
        parent_tab_widget.addTab(self.hvac_config_tab, "Climate Settings")
