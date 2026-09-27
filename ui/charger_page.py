"""Shared EV charger status and decision-history page."""

import datetime
import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


class ChargerDecisionChart(QWidget):
    """Plots the live inputs used by the charger controller over four hours."""

    HISTORY_SECONDS = 4 * 60 * 60

    def __init__(self):
        super().__init__()
        self.samples = []
        self.limits = {}
        self.setMinimumHeight(260)

    def add_status(self, status):
        try:
            timestamp = float(status.get("timestamp", time.time()))
            grid_flow = float(status["grid_flow_watts"])
            battery_soc = float(status["battery_soc"])
            target_amps = int(status.get("target_amps", 0))
        except (KeyError, TypeError, ValueError):
            return
        self.limits = dict(status.get("limits") or self.limits)
        self.samples.append((timestamp, grid_flow, battery_soc, target_amps))
        cutoff = timestamp - self.HISTORY_SECONDS
        self.samples = [sample for sample in self.samples if sample[0] >= cutoff]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        left, right, top, bottom = 58, 54, 38, 42
        plot = QRectF(
            left,
            top,
            max(1, self.width() - left - right),
            max(1, self.height() - top - bottom),
        )
        painter.setPen(QColor("#202020"))
        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        painter.drawText(
            8,
            16,
            "Charging decision inputs (last 4 hours)",
        )
        painter.setFont(QFont("Arial", 8))
        painter.drawText(
            8,
            31,
            "Grid flow: blue (negative = export) | Battery SOC: purple | "
            "Charging state: green strip",
        )
        painter.setPen(QPen(QColor("#202020"), 1))
        painter.drawRect(plot)

        start_watts = self._number("surplus_start_watts", -2000.0)
        stop_watts = self._number("surplus_stop_watts", -2000.0)
        grid_values = [sample[1] for sample in self.samples] + [
            0.0,
            start_watts,
            stop_watts,
        ]
        grid_min = min(grid_values)
        grid_max = max(grid_values)
        grid_padding = max(300.0, (grid_max - grid_min) * 0.1)
        grid_min -= grid_padding
        grid_max += grid_padding

        window_end = self.samples[-1][0] if self.samples else time.time()
        window_start = window_end - self.HISTORY_SECONDS

        def point_for(timestamp, grid_flow):
            x = plot.left() + (
                (timestamp - window_start) / self.HISTORY_SECONDS * plot.width()
            )
            y = plot.bottom() - (
                (grid_flow - grid_min) / (grid_max - grid_min) * plot.height()
            )
            return QPointF(x, y)

        for offset in range(5):
            x = plot.left() + plot.width() * offset / 4
            painter.setPen(QPen(QColor("#e0e0e0"), 1))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(QColor("#505050"))
            painter.drawText(
                int(x - 16),
                self.height() - 8,
                datetime.datetime.fromtimestamp(
                    window_start + offset * self.HISTORY_SECONDS / 4
                ).strftime("%H:%M"),
            )

        for value in (grid_min, 0.0, grid_max):
            y = point_for(window_start, value).y()
            painter.setPen(QPen(QColor("#d8d8d8"), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor("#505050"))
            painter.drawText(
                QRectF(0, y - 8, left - 5, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{value:.0f}",
            )

        self._draw_threshold(
            painter,
            plot,
            point_for,
            start_watts,
            QColor("#28a745"),
            "Start",
        )
        if stop_watts == start_watts:
            painter.setPen(QColor("#505050"))
            painter.drawText(
                plot.left() + 4,
                int(point_for(window_start, stop_watts).y() + 22),
                "Stop: same threshold",
            )
        else:
            self._draw_threshold(
                painter,
                plot,
                point_for,
                stop_watts,
                QColor("#d62728"),
                "Stop",
            )

        painter.setPen(QColor("#9467bd"))
        painter.drawText(
            QRectF(plot.right() + 4, plot.top() - 8, right - 6, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "SOC",
        )
        for percent in (0, 50, 100):
            y = plot.bottom() - percent / 100 * plot.height()
            painter.setPen(QColor("#9467bd"))
            painter.drawText(
                QRectF(plot.right() + 4, y - 8, right - 6, 16),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{percent}%",
            )

        for first, second in zip(self.samples, self.samples[1:]):
            painter.setPen(QPen(QColor("#1f5fbf"), 2))
            painter.drawLine(
                point_for(first[0], first[1]),
                point_for(second[0], second[1]),
            )
            painter.setPen(QPen(QColor("#9467bd"), 2))
            painter.drawLine(
                QPointF(
                    point_for(first[0], first[1]).x(),
                    plot.bottom() - first[2] / 100 * plot.height(),
                ),
                QPointF(
                    point_for(second[0], second[1]).x(),
                    plot.bottom() - second[2] / 100 * plot.height(),
                ),
            )

            if first[3] > 0:
                start = point_for(first[0], first[1]).x()
                end = point_for(second[0], second[1]).x()
                painter.setPen(QPen(QColor("#28a745"), 5))
                painter.drawLine(
                    QPointF(start, plot.bottom() - 4),
                    QPointF(end, plot.bottom() - 4),
                )

        if not self.samples:
            painter.setPen(QColor("#606060"))
            painter.drawText(
                plot,
                Qt.AlignmentFlag.AlignCenter,
                "Waiting for charger status",
            )

    def _number(self, key, fallback):
        try:
            return float(self.limits.get(key, fallback))
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _draw_threshold(painter, plot, point_for, watts, color, label):
        y = point_for(0, watts).y()
        painter.setPen(QPen(color, 1.5, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        painter.setPen(color)
        painter.drawText(plot.left() + 4, int(y - 4), f"{label}: {watts:.0f} W")


class ChargerStatusPage(QWidget):
    """Shows EV charger limits, its current command, and decision history."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.state_label = QLabel("Charger: Waiting for status")
        self.state_label.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.state_label)

        self.current_label = QLabel()
        self.current_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        layout.addWidget(self.current_label)

        self.limits_label = QLabel()
        self.limits_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.limits_label.setWordWrap(True)
        layout.addWidget(self.limits_label)

        self.chart = ChargerDecisionChart()
        layout.addWidget(self.chart, 1)

    def refresh_status(self, status):
        if not status:
            return
        try:
            target_amps = int(status.get("target_amps", 0))
            grid_flow = float(status.get("grid_flow_watts", 0.0))
            battery_soc = float(status.get("battery_soc", 0.0))
        except (TypeError, ValueError):
            self.state_label.setText("Charger: Invalid status received")
            return

        state = "Charging" if target_amps > 0 else "Off"
        color = "#28a745" if target_amps > 0 else "#606060"
        self.state_label.setText(f"Charger: {state}")
        self.state_label.setStyleSheet(f"color: {color};")
        mode = "Off-peak" if status.get("is_off_peak") else "Solar surplus"
        self.current_label.setText(
            f"Command: {target_amps} A ({mode})  |  "
            f"Grid: {grid_flow:.0f} W  |  Battery: {battery_soc:.0f}%"
        )

        limits = status.get("limits") or {}
        self.limits_label.setText(
            "Limits: "
            f"Off-peak {limits.get('off_peak_amps', '--')} A | "
            f"Solar start {limits.get('surplus_start_watts', '--')} W | "
            f"Solar stop {limits.get('surplus_stop_watts', '--')} W | "
            f"Solar current {limits.get('minimum_solar_amps', '--')}–"
            f"{limits.get('maximum_solar_amps', '--')} A | "
            f"Battery reserve {limits.get('battery_reserve_soc', '--')}%"
        )
        self.chart.add_status(status)
