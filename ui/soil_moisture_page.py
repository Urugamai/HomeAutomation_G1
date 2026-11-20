import datetime

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from libraries.rain_history import (
    RainHistoryStore, daily_series, hourly_series, monthly_series,
)
from libraries.rain_history import totals as rain_totals
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
        self.setMinimumSize(110, 130)

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


class RainChart(QWidget):
    """Bar chart of rain: last 24 hours, last 7 days or last 12 months."""

    MODES = ("24 h", "Week", "Year")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = 0
        self.data = RainHistoryStore._empty()
        self.now = datetime.datetime.now()
        self.setFixedHeight(80)

    def set_mode(self, mode):
        self.mode = mode
        self.update()

    def set_data(self, data, now):
        self.data = data
        self.now = now
        self.update()

    def bars(self):
        if self.mode == 0:
            return [(f"{start:%H}", mm) for start, mm in hourly_series(self.data, self.now)]
        if self.mode == 1:
            return [(f"{day:%a}", mm) for day, mm in daily_series(self.data, self.now, 7)]
        return [(f"{month:%b}", mm) for month, mm in monthly_series(self.data, self.now)]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bars = self.bars()
        left, right, top, bottom = 34, 6, 8, 18
        plot = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
        peak = max([mm for _, mm in bars] + [1.0])
        painter.setPen(QColor("#505050"))
        painter.setFont(QFont("Arial", 7))
        painter.drawText(QRectF(0, top - 6, left - 4, 12),
                         Qt.AlignmentFlag.AlignRight, f"{peak:.0f}" if peak >= 10 else f"{peak:.1f}")
        painter.drawText(QRectF(0, plot.bottom() - 6, left - 4, 12),
                         Qt.AlignmentFlag.AlignRight, "0")
        painter.setPen(QColor("#d0d0d0"))
        painter.drawLine(plot.bottomLeft(), plot.bottomRight())
        slot = plot.width() / len(bars)
        for index, (label, mm) in enumerate(bars):
            x = plot.left() + index * slot
            if mm > 0:
                height = plot.height() * mm / peak
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#2e86de"))
                painter.drawRect(QRectF(x + slot * 0.15, plot.bottom() - height, slot * 0.7, height))
            if len(bars) <= 12 or index % 3 == 0:
                painter.setPen(QColor("#505050"))
                painter.drawText(QRectF(x - 4, plot.bottom() + 1, slot + 8, bottom - 1),
                                 Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)


class SoilMoisturePage(QWidget):
    """Bar graph per Ecowitt soil moisture sensor (moisture and battery), plus rain."""

    COLUMNS = 6

    def __init__(self, rain_history=None):
        super().__init__()
        self.rain_history = rain_history or RainHistoryStore()
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

        rain_header = QHBoxLayout()
        rain_title = QLabel("Rain")
        rain_title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        rain_header.addWidget(rain_title)
        self.rain_buttons = []
        for index, label in enumerate(RainChart.MODES):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _=False, i=index: self._set_rain_mode(i))
            rain_header.addWidget(button)
            self.rain_buttons.append(button)
        self.rain_totals_label = QLabel("")
        self.rain_totals_label.setStyleSheet("font-size: 9pt;")
        rain_header.addWidget(self.rain_totals_label, 1)
        layout.addLayout(rain_header)
        self.rain_chart = RainChart()
        layout.addWidget(self.rain_chart)
        self._rain_rate = None
        self._update_rain()

    def _set_rain_mode(self, mode):
        for index, button in enumerate(self.rain_buttons):
            button.setChecked(index == mode)
        self.rain_chart.set_mode(mode)

    def _update_rain(self):
        self.rain_history.reload()
        now = datetime.datetime.now()
        self.rain_chart.set_data(self.rain_history.data, now)
        sums = rain_totals(self.rain_history.data, now)
        rate = "" if self._rain_rate is None else f"Rate {self._rain_rate:.1f} mm/h  ·  "
        self.rain_totals_label.setText(
            f"{rate}Today {sums['day']:.1f}  ·  7 days {sums['week']:.1f}  ·  "
            f"Month {sums['month']:.1f}  ·  Year {sums['year']:.1f} mm"
        )

    def refresh_sources(self, sources):
        outdoor = (sources or {}).get("Ecowitt", {})
        rate = outdoor.get("rain_rate") if isinstance(outdoor, dict) else None
        self._rain_rate = rate if isinstance(rate, (int, float)) else None
        self._update_rain()
        sensors = soil_sensors(outdoor)
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
