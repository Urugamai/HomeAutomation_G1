from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from PyQt6.QtCore import QTimer, QTime, QDate, Qt
from PyQt6.QtGui import QFont, QColor, QPalette


class BiDirectionalFlowWidget(QWidget):
    """Displays battery or grid load balances around zero."""

    def __init__(self, label_text: str):
        super().__init__()
        layout = QVBoxLayout(self)
        self.lbl = QLabel(label_text)
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        layout.addWidget(self.lbl)

        self.bar = QProgressBar()
        self.bar.setRange(-5000, 5000)
        self.bar.setValue(0)
        self.bar.setFormat("%v W")
        layout.addWidget(self.bar)

    def update_flow_value(self, value: int):
        self.bar.setValue(value)
        palette = self.bar.palette()
        if value < -100:  # Draining or Exporting (Red)
            palette.setColor(QPalette.ColorRole.Highlight, QColor(220, 50, 50))
        elif value > 100:  # Charging or Importing (Green)
            palette.setColor(QPalette.ColorRole.Highlight, QColor(50, 200, 50))
        else:  # Margin Deadband (Grey)
            palette.setColor(QPalette.ColorRole.Highlight, QColor(150, 150, 150))
        self.bar.setPalette(palette)


class TouchDashboard(QWidget):
    def __init__(self):
        super().__init__()
        main_layout = QVBoxLayout(self)

        # High-visibility clock
        self.time_lbl = QLabel()
        self.time_lbl.setFont(QFont("Monospace", 36, QFont.Weight.Bold))
        self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.time_lbl)

        # Environment status readouts
        self.temp_lbl = QLabel("Reading telemetry...")
        self.temp_lbl.setFont(QFont("Arial", 14))
        self.temp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.temp_lbl)

        # Energy Panel Layout
        energy_layout = QHBoxLayout()

        self.soc_bar = QProgressBar()
        self.soc_bar.setOrientation(Qt.Orientation.Vertical)
        self.soc_bar.setRange(0, 100)

        self.battery_widget = BiDirectionalFlowWidget("Battery Flow")
        self.grid_widget = BiDirectionalFlowWidget("Grid Flow")

        energy_layout.addWidget(QLabel("SOC %:"))
        energy_layout.addWidget(self.soc_bar)
        energy_layout.addWidget(self.battery_widget)
        energy_layout.addWidget(self.grid_widget)

        main_layout.addLayout(energy_layout)

        # Clock updates
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_time)
        self.timer.start(1000)

    def _refresh_time(self):
        now = QTime.currentTime().toString("hh:mm:ss")
        date = QDate.currentDate().toString("ddd dd MMM yyyy")
        self.time_lbl.setText(f"{now}\n{date}")

    def refresh_telemetry(self, data: dict):
        self.temp_lbl.setText(f"Inside: {data['inside_temp']}°C  |  Outside: {data['outside_temp']}°C")
        self.soc_bar.setValue(data['battery_soc'])
        self.battery_widget.update_flow_value(data['battery_flow'])
        self.grid_widget.update_flow_value(data['grid_flow'])
