from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from libraries.soil_moisture import (
    battery_color, battery_fraction, battery_text, moisture_color, soil_sensors,
)


class SoilSensorBars(QWidget):
    """Paints one sensor: a moisture % bar with an adjacent battery bar."""

    def __init__(self, channel, parent=None):
        super().__init__(parent)
        self.channel = channel
        self.name = f"Soil {channel}"
        self.moisture = None
        self.battery = None
        self.setMinimumSize(110, 185)

    def set_values(self, moisture, battery, name=None):
        self.moisture = moisture
        self.battery = battery
        self.name = name or f"Soil {self.channel}"
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        label_h = 34
        top = 18
        bottom = height - label_h
        bar_h = max(10, bottom - top)
        moisture_x = width * 0.18
        bar_w = width * 0.28
        battery_x = moisture_x + bar_w + width * 0.08
        track = QColor("#e2e6ea")

        painter.setPen(QColor("#303030"))
        painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        painter.drawText(
            QRectF(2, height - label_h + 2, width - 4, label_h - 2),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap, self.name)

        for x, fraction, color, text in (
            (
                moisture_x,
                None if self.moisture is None
                else max(0.0, min(1.0, self.moisture / 100.0)),
                None if self.moisture is None else moisture_color(self.moisture),
                "--" if self.moisture is None else f"{self.moisture:.0f}%",
            ),
            (
                battery_x,
                None if self.battery is None else battery_fraction(self.battery),
                None if self.battery is None else battery_color(self.battery),
                "--" if self.battery is None else battery_text(self.battery),
            ),
        ):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track)
            painter.drawRoundedRect(QRectF(x, top, bar_w, bar_h), 3, 3)
            if fraction is not None:
                fill_h = bar_h * fraction
                painter.setBrush(QColor(color))
                painter.drawRoundedRect(
                    QRectF(x, top + bar_h - fill_h, bar_w, fill_h), 3, 3)
            painter.setPen(QColor("#303030"))
            painter.setFont(QFont("Arial", 8))
            painter.drawText(
                QRectF(x - 12, 0, bar_w + 24, label_h),
                Qt.AlignmentFlag.AlignCenter, text)


class SoilMoisturePage(QWidget):
    """Bar graph per Ecowitt soil moisture sensor (moisture and battery)."""

    COLUMNS = 6

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("Soil Moisture")
        title.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        layout.addWidget(title)
        self.status_label = QLabel("Waiting for soil moisture sensors...")
        layout.addWidget(self.status_label)
        legend = QLabel(
            "Left bar: moisture (green 30-70%, amber 15-30% / 70-90%, "
            "red outside). Right bar: battery (red = replace)."
        )
        legend.setStyleSheet("font-size: 8pt; color: #505050;")
        layout.addWidget(legend)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.grid = QGridLayout(container)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)
        self._widgets = {}

    def refresh_sources(self, sources):
        sensors = soil_sensors((sources or {}).get("Ecowitt", {}))
        wanted = {channel for channel, _, _, _ in sensors}
        for channel in [c for c in self._widgets if c not in wanted]:
            widget = self._widgets.pop(channel)
            self.grid.removeWidget(widget)
            widget.deleteLater()
        for channel, moisture, battery, name in sensors:
            widget = self._widgets.get(channel)
            if widget is None:
                widget = SoilSensorBars(channel)
                self._widgets[channel] = widget
                index = len(self._widgets) - 1
                self.grid.addWidget(widget, index // self.COLUMNS, index % self.COLUMNS)
            widget.set_values(moisture, battery, name)
        self._relayout(sensors)
        self.status_label.setText(
            f"{len(sensors)} soil moisture sensors" if sensors
            else "No soil moisture sensors reporting"
        )

    def _relayout(self, sensors):
        for position, (channel, _, _, _) in enumerate(sensors):
            widget = self._widgets[channel]
            self.grid.removeWidget(widget)
            self.grid.addWidget(widget, position // self.COLUMNS, position % self.COLUMNS)
