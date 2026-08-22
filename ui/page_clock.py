from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from PyQt6.QtCore import QTimer, QTime, QDate, Qt
from PyQt6.QtGui import QFont, QColor, QPalette

class CustomBiDirectionalBar(QWidget):
    def __init__(self, label_text: str):
        super().__init__()
        layout = QVBoxLayout(self)
        self.lbl = QLabel(label_text)
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl)
        self.bar = QProgressBar()
        self.bar.setRange(-5000, 5000)
        self.bar.setValue(0)
        self.bar.setFormat("%v W")
        layout.addWidget(self.bar)

    def update_flow(self, value: int):
        self.bar.setValue(value)
        palette = self.bar.palette()
        if value < -100:
            palette.setColor(QPalette.ColorRole.Highlight, QColor(220, 50, 50))
        elif value > 100:
            palette.setColor(QPalette.ColorRole.Highlight, QColor(50, 200, 50))
        else:
            palette.setColor(QPalette.ColorRole.Highlight, QColor(150, 150, 150))
        self.bar.setPalette(palette)

class ClockDashboardPage(QWidget):
    def __init__(self):
        super().__init__()
        main_layout = QVBoxLayout(self)
        self.time_lbl = QLabel()
        self.time_lbl.setFont(QFont("Monospace", 48, QFont.Weight.Bold))
        self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.time_lbl)

        self.temp_lbl = QLabel("Inside: --°C | Outside: --°C")
        self.temp_lbl.setFont(QFont("Arial", 16))
        self.temp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.temp_lbl)

        metrics_layout = QHBoxLayout()
        self.soc_bar = QProgressBar()
        self.soc_bar.setOrientation(Qt.Orientation.Vertical)
        self.soc_bar.setRange(0, 100)
        self.soc_bar.setValue(0)
        
        self.battery_flow_widget = CustomBiDirectionalBar("Battery Power Flow")
        self.grid_flow_widget = CustomBiDirectionalBar("Grid Power Flow")

        metrics_layout.addWidget(QLabel("SOC:"))
        metrics_layout.addWidget(self.soc_bar)
        metrics_layout.addLayout(self.battery_flow_widget.layout())
        metrics_layout.addLayout(self.grid_flow_widget.layout())
        main_layout.addLayout(metrics_layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_clock_tick)
        self.timer.start(1000)

    def _update_clock_tick(self):
        now = QTime.currentTime().toString("hh:mm:ss")
        date = QDate.currentDate().toString("ddd dd MMM yyyy")
        self.time_lbl.setText(f"{now}\n{date}")

    def update_telemetry(self, inside: float, outside: float, soc: int, bat_w: int, grid_w: int):
        self.temp_lbl.setText(f"Inside: {inside:.1f}°C | Outside: {outside:.1f}°C")
        self.soc_bar.setValue(soc)
        self.battery_flow_widget.update_flow(bat_w)
        self.grid_flow_widget.update_flow(grid_w)
