import datetime
import json
import logging
import math
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSpinBox,
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QPointF, QRectF
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen

from libraries.hvac_settings import HvacSettingsStore

LOGGER = logging.getLogger(__name__)


class ClimateHistoryStore:
    """Persists a rolling climate and HVAC relay history for validation."""

    STORAGE_PATH = Path("/mnt/WatsonHome/home_climate_history.json")
    RETENTION_PERIOD = datetime.timedelta(hours=24)

    def __init__(self, storage_path=None):
        self.storage_path = Path(storage_path or self.STORAGE_PATH)
        self.samples = []
        self._storage_warning_logged = False
        self._load_recent()

    def _load_recent(self):
        if not self.storage_path.is_file():
            return
        try:
            with self.storage_path.open("r", encoding="utf-8") as history_file:
                payload = json.load(history_file)
            self.samples = [
                {
                    **item,
                    "timestamp": datetime.datetime.fromisoformat(item["timestamp"]),
                }
                for item in payload.get("samples", [])
            ]
            self._prune(datetime.datetime.now())
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            LOGGER.warning("Unable to load climate history from %s: %s", self.storage_path, exc)
            self.samples = []

    def _prune(self, reference_time):
        cutoff = reference_time - self.RETENTION_PERIOD
        self.samples = [
            sample
            for sample in self.samples
            if cutoff <= sample["timestamp"] <= reference_time
        ]

    def add_sample(
        self,
        timestamp,
        indoor_temperatures,
        outdoor_temperature,
        heating_setpoint,
        cooling_setpoint,
        heater_on,
        cooler_on,
        fan_on,
    ):
        self._prune(timestamp)
        self.samples.append(
            {
                "timestamp": timestamp,
                "indoor_temperatures": dict(indoor_temperatures),
                "outdoor_temperature": outdoor_temperature,
                "heating_setpoint": float(heating_setpoint),
                "cooling_setpoint": float(cooling_setpoint),
                "heater_on": bool(heater_on),
                "cooler_on": bool(cooler_on),
                "fan_on": bool(fan_on),
            }
        )
        self._write()

    def _write(self):
        if not self.storage_path.parent.is_dir():
            if not self._storage_warning_logged:
                LOGGER.warning(
                    "Climate history storage is unavailable: %s",
                    self.storage_path.parent,
                )
                self._storage_warning_logged = True
            return

        payload = {
            "samples": [
                {
                    **sample,
                    "timestamp": sample["timestamp"].isoformat(timespec="seconds"),
                }
                for sample in self.samples
            ]
        }
        temporary_path = self.storage_path.with_suffix(".tmp")
        try:
            with temporary_path.open("w", encoding="utf-8") as history_file:
                json.dump(payload, history_file, separators=(",", ":"))
                history_file.flush()
                os.fsync(history_file.fileno())
            os.replace(temporary_path, self.storage_path)
        except OSError as exc:
            LOGGER.warning("Unable to save climate history to %s: %s", self.storage_path, exc)
            try:
                temporary_path.unlink()
            except OSError:
                pass


class ClimateValidationChart(QWidget):
    """Plots sensor temperatures and HVAC output command intervals."""

    INDOOR_COLORS = (
        QColor("#2ca02c"),
        QColor("#9467bd"),
        QColor("#17becf"),
        QColor("#e377c2"),
        QColor("#bcbd22"),
    )

    def __init__(self):
        super().__init__()
        self.samples = []
        self.setMinimumHeight(250)

    def set_samples(self, samples):
        self.samples = list(samples)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        source_names = sorted(
            {
                source
                for sample in self.samples
                for source in sample.get("indoor_temperatures", {})
            }
        )

        left, right, top, bottom = 52, 24, 58, 30
        plot = QRectF(
            left,
            top,
            max(1, self.width() - left - right),
            max(1, self.height() - top - bottom),
        )
        window_end = datetime.datetime.now()
        window_start = window_end - ClimateHistoryStore.RETENTION_PERIOD

        painter.setPen(QPen(QColor("#202020"), 1))
        painter.drawText(8, 16, "Climate validation (last 24 hours)")
        indoor_label = "Indoor sensors:"
        painter.drawText(8, 32, indoor_label)
        legend_x = 8 + painter.fontMetrics().horizontalAdvance(indoor_label) + 8
        for index, source in enumerate(source_names):
            painter.setPen(self.INDOOR_COLORS[index % len(self.INDOOR_COLORS)])
            painter.drawText(legend_x, 32, source)
            legend_x += painter.fontMetrics().horizontalAdvance(source) + 14
        painter.setPen(QPen(QColor("#202020"), 1))
        painter.drawText(
            8,
            48,
            "Outdoor: black | "
            "Cool: blue | Heat: brown | Fan: gray | Fault: red",
        )
        painter.drawRect(plot)

        temperatures = []
        for sample in self.samples:
            temperatures.extend(sample.get("indoor_temperatures", {}).values())
            outdoor = sample.get("outdoor_temperature")
            if outdoor is not None:
                temperatures.append(outdoor)
            temperatures.extend(
                (
                    sample.get("heating_setpoint"),
                    sample.get("cooling_setpoint"),
                )
            )
        temperatures = [float(value) for value in temperatures if value is not None]
        if temperatures:
            chart_min = math.floor(min(temperatures) - 1.0)
            chart_max = math.ceil(max(temperatures) + 1.0)
            if chart_max <= chart_min:
                chart_max = chart_min + 2.0
        else:
            chart_min, chart_max = 15.0, 30.0

        def point_for(timestamp, temperature):
            seconds = (timestamp - window_start).total_seconds()
            x = plot.left() + plot.width() * seconds / ClimateHistoryStore.RETENTION_PERIOD.total_seconds()
            y = plot.bottom() - (
                (temperature - chart_min) / (chart_max - chart_min) * plot.height()
            )
            return QPointF(x, y)

        for hour in range(0, 25, 2):
            x = plot.left() + plot.width() * hour / 24
            painter.setPen(QPen(QColor("#e0e0e0"), 1))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(QColor("#404040"))
            painter.setFont(QFont("Arial", 8))
            painter.drawText(
                int(x - 14),
                self.height() - 8,
                (window_start + datetime.timedelta(hours=hour)).strftime("%H:%M"),
            )

        step = 1.0 if chart_max - chart_min <= 12.0 else 2.0
        tick = math.ceil(chart_min / step) * step
        while tick <= chart_max + 1e-6:
            y = point_for(window_start, tick).y()
            painter.setPen(QPen(QColor("#eaeaea"), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor("#505050"))
            painter.setFont(QFont("Arial", 8))
            painter.drawText(
                QRectF(0, y - 8, left - 6, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{tick:.0f}°",
            )
            tick += step

        for first, second in zip(self.samples, self.samples[1:]):
            start = point_for(first["timestamp"], chart_min).x()
            end = point_for(second["timestamp"], chart_min).x()
            heater_on = first.get("heater_on", False)
            cooler_on = first.get("cooler_on", False)
            fan_on = first.get("fan_on", False)
            unsafe = (heater_on and cooler_on) or (
                (heater_on or cooler_on) and not fan_on
            )
            if unsafe:
                painter.setBrush(QBrush(QColor(220, 53, 69, 105)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(QRectF(start, plot.top(), end - start, plot.height()))
            elif cooler_on:
                target_y = point_for(first["timestamp"], first["cooling_setpoint"]).y()
                painter.setBrush(QBrush(QColor(0, 122, 255, 85)))
                painter.setPen(QPen(QColor("#007aff"), 1))
                painter.drawRect(QRectF(start, target_y, end - start, plot.bottom() - target_y))
            elif heater_on:
                target_y = point_for(first["timestamp"], first["heating_setpoint"]).y()
                painter.setBrush(QBrush(QColor(139, 69, 19, 85)))
                painter.setPen(QPen(QColor("#8b4513"), 1))
                painter.drawRect(QRectF(start, target_y, end - start, plot.bottom() - target_y))

            if fan_on:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(128, 128, 128, 180)))
                painter.drawRect(QRectF(start, plot.bottom() - 6, end - start, 6))

        for index, source in enumerate(source_names):
            painter.setPen(QPen(self.INDOOR_COLORS[index % len(self.INDOOR_COLORS)], 2))
            for first, second in zip(self.samples, self.samples[1:]):
                first_temperature = first.get("indoor_temperatures", {}).get(source)
                second_temperature = second.get("indoor_temperatures", {}).get(source)
                if first_temperature is not None and second_temperature is not None:
                    painter.drawLine(
                        point_for(first["timestamp"], first_temperature),
                        point_for(second["timestamp"], second_temperature),
                    )

        painter.setPen(QPen(QColor("#202020"), 2, Qt.PenStyle.DashLine))
        for first, second in zip(self.samples, self.samples[1:]):
            first_temperature = first.get("outdoor_temperature")
            second_temperature = second.get("outdoor_temperature")
            if first_temperature is not None and second_temperature is not None:
                painter.drawLine(
                    point_for(first["timestamp"], first_temperature),
                    point_for(second["timestamp"], second_temperature),
                )

        if not self.samples:
            painter.setPen(QColor("#606060"))
            painter.setFont(QFont("Arial", 10))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Waiting for climate samples")


class HvacConfigurationPage(QWidget):
    """
    Touchscreen optimized HVAC input panel.
    Emits a structured JSON signal whenever a setpoint or target bound is updated.
    """
    # Event custom emitter passing target payload structures back to the MQTT driver
    settings_changed = pyqtSignal(dict)
    command_requested = pyqtSignal(dict)

    def __init__(self):
        super().__init__()

        # Internal configuration defaults
        self.t_min = 20.0
        self.t_max = 24.0
        self.fan_preheat_seconds = 60
        self.fan_postrun_seconds = 120
        self.min_run_seconds = 300
        self.max_run_seconds = 600
        self.rest_seconds = 300
        self.settings_store = HvacSettingsStore()
        saved_settings = self.settings_store.load()
        if saved_settings:
            self._set_settings_values(saved_settings)
        self.system_mode = "OFF"
        self.is_resting = False

        # Central Layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(10)
        self.main_layout.setContentsMargins(15, 15, 15, 15)

        # Build Interactive Temperature Selectors
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self._build_temp_picker("Min Target (Heat)", "t_min"))

        controls_layout.addWidget(self._build_vertical_separator())
        controls_layout.addWidget(self._build_average_temperature_display())
        controls_layout.addWidget(self._build_vertical_separator())

        controls_layout.addWidget(self._build_temp_picker("Max Target (Cool)", "t_max"))
        self.main_layout.addLayout(controls_layout)

        timings_layout = QHBoxLayout()
        timings_layout.addWidget(
            self._build_duration_picker(
                "Fan lead", "fan_preheat_seconds", 0, 600, 15
            )
        )
        timings_layout.addWidget(
            self._build_duration_picker(
                "Fan post-run", "fan_postrun_seconds", 0, 900, 15
            )
        )
        timings_layout.addWidget(
            self._build_duration_picker(
                "Minimum run", "min_run_seconds", 60, 1800, 30
            )
        )
        timings_layout.addWidget(
            self._build_duration_picker(
                "Maximum run", "max_run_seconds", 60, 3600, 30
            )
        )
        timings_layout.addWidget(
            self._build_duration_picker("Rest period", "rest_seconds", 0, 1800, 30)
        )
        self.main_layout.addLayout(timings_layout)

        relay_layout = QHBoxLayout()
        relay_layout.setSpacing(10)
        self.heater_relay_indicator = self._build_relay_indicator(
            "Heater", "HEATING"
        )
        self.cooler_relay_indicator = self._build_relay_indicator(
            "Cooler", "COOLING"
        )
        self.fan_relay_indicator = self._build_relay_indicator("Fan", "FAN")
        relay_layout.addWidget(self.heater_relay_indicator)
        relay_layout.addWidget(self.cooler_relay_indicator)
        relay_layout.addWidget(self.fan_relay_indicator)
        self.main_layout.addLayout(relay_layout)

        self.auto_control_button = QPushButton("Return to automatic control")
        self.auto_control_button.setMinimumHeight(36)
        self.auto_control_button.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.auto_control_button.clicked.connect(
            lambda: self.command_requested.emit({"action": "AUTO"})
        )
        self.main_layout.addWidget(self.auto_control_button)

        # Diagnostics / Status Bar Footer Readout
        self.status_lbl = QLabel("System Status: Idle (OFF) | Interlocks Free")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setFont(QFont("Arial", 11, QFont.Weight.Medium))
        self.status_lbl.setStyleSheet("color: #777777;")
        self.main_layout.addWidget(self.status_lbl)

        self.climate_history = ClimateHistoryStore()
        self.climate_chart = ClimateValidationChart()
        self.climate_chart.set_samples(self.climate_history.samples)
        self.main_layout.addWidget(self.climate_chart, 1)
        self._latest_climate_telemetry = None
        self.climate_sample_timer = QTimer(self)
        self.climate_sample_timer.timeout.connect(self._record_climate_sample)
        self.climate_sample_timer.start(15_000)

    def _build_temp_picker(self, title_text: str, target_var: str) -> QWidget:
        """Helper matrix producing large touch-friendly increment panels."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)

        title = QLabel(title_text)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        layout.addWidget(title)

        val_display = QLabel()
        val_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val_display.setFont(QFont("Monospace", 24, QFont.Weight.Bold))
        setattr(self, f"{target_var}_lbl", val_display)
        layout.addWidget(val_display)

        # Button Grid Wrapper
        btn_layout = QHBoxLayout()
        btn_down = QPushButton("- 0.5")
        btn_down.setMinimumHeight(45)  # Large target matching fat-finger touch profiles
        btn_down.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        btn_down.clicked.connect(lambda: self._adjust_value(target_var, -0.5))

        btn_up = QPushButton("+ 0.5")
        btn_up.setMinimumHeight(45)
        btn_up.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        btn_up.clicked.connect(lambda: self._adjust_value(target_var, 0.5))

        btn_layout.addWidget(btn_down)
        btn_layout.addWidget(btn_up)
        layout.addLayout(btn_layout)

        return container

    @staticmethod
    def _build_vertical_separator() -> QFrame:
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        return separator

    def _build_average_temperature_display(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)

        title = QLabel("Average House Temperature")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        layout.addWidget(title)

        self.average_house_temp_lbl = QLabel("--")
        self.average_house_temp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.average_house_temp_lbl.setFont(QFont("Monospace", 24, QFont.Weight.Bold))
        layout.addWidget(self.average_house_temp_lbl)
        layout.addStretch(1)
        return container

    def _build_duration_picker(
        self, title_text: str, target_var: str, minimum: int, maximum: int, step: int
    ) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)

        title = QLabel(title_text)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(title)

        picker = QSpinBox()
        picker.setRange(minimum, maximum)
        picker.setSingleStep(step)
        picker.setSuffix(" s")
        picker.setValue(getattr(self, target_var))
        picker.setMinimumHeight(45)
        picker.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        picker.valueChanged.connect(
            lambda value: self._set_duration(target_var, value)
        )
        setattr(self, f"{target_var}_picker", picker)
        layout.addWidget(picker)
        return container

    def _build_relay_indicator(self, name: str, action: str) -> QPushButton:
        indicator = QPushButton(f"{name}\nOFF")
        indicator.setMinimumHeight(54)
        indicator.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        indicator.setStyleSheet(
            "background-color: #eeeeee; color: #606060; "
            "border: 1px solid #aaaaaa; border-radius: 4px;"
        )
        indicator.clicked.connect(
            lambda: self.command_requested.emit({"action": action})
        )
        return indicator

    @staticmethod
    def _set_relay_indicator(
        indicator: QPushButton,
        name: str,
        is_on: bool,
        color: str,
    ):
        if is_on:
            indicator.setText(f"{name}\nON")
            indicator.setStyleSheet(
                f"background-color: {color}; color: white; "
                "border: 1px solid #555555; border-radius: 4px;"
            )
        else:
            indicator.setText(f"{name}\nOFF")
            indicator.setStyleSheet(
                "background-color: #eeeeee; color: #606060; "
                "border: 1px solid #aaaaaa; border-radius: 4px;"
            )

    def _adjust_value(self, target_var: str, amount: float):
        """Processes logic steps securely before formatting outbound communication payloads."""
        current_val = getattr(self, target_var)
        new_val = round(current_val + amount, 1)

        # Continuous sanity checking boundary parameters
        if target_var == "t_min" and new_val >= self.t_max:
            return  # Block overlap: Min heating point can't exceed or meet cooling points
        if target_var == "t_max" and new_val <= self.t_min:
            return  # Block overlap

        # Commit variations
        setattr(self, target_var, new_val)
        self.update_display_metrics()
        self._emit_current_configuration()

    def _set_duration(self, target_var: str, value: int):
        new_value = int(value)
        if target_var == "min_run_seconds" and new_value > self.max_run_seconds:
            getattr(self, f"{target_var}_picker").setValue(self.min_run_seconds)
            return
        if target_var == "max_run_seconds" and new_value < self.min_run_seconds:
            getattr(self, f"{target_var}_picker").setValue(self.max_run_seconds)
            return
        setattr(self, target_var, new_value)
        self._emit_current_configuration()

    def apply_settings(self, settings: dict):
        if not settings:
            return
        try:
            normalized = self.settings_store.normalize(settings)
            changed = normalized != self._settings_payload()
            self._set_settings_values(normalized)
            for target_var in (
                "fan_preheat_seconds",
                "fan_postrun_seconds",
                "min_run_seconds",
                "max_run_seconds",
                "rest_seconds",
            ):
                picker = getattr(self, f"{target_var}_picker")
                picker.blockSignals(True)
                picker.setValue(int(getattr(self, target_var)))
                picker.blockSignals(False)
            self.update_display_metrics()
            if changed:
                self.settings_store.save(normalized)
        except (TypeError, ValueError) as error:
            print(f"[HVAC SETTINGS ERROR] Ignoring invalid retained settings: {error}")
            return
        except OSError as error:
            print(
                f"[HVAC SETTINGS ERROR] Settings applied but could not be saved: {error}"
            )

    def _set_settings_values(self, settings):
        self.t_min = float(settings["target_min"])
        self.t_max = float(settings["target_max"])
        self.fan_preheat_seconds = int(settings["fan_preheat_seconds"])
        self.fan_postrun_seconds = int(settings["fan_postrun_seconds"])
        self.min_run_seconds = int(settings["min_run_seconds"])
        self.max_run_seconds = int(settings["max_run_seconds"])
        self.rest_seconds = int(settings["rest_seconds"])

    def _settings_payload(self):
        return {
            "target_min": self.t_min,
            "target_max": self.t_max,
            "fan_preheat_seconds": self.fan_preheat_seconds,
            "fan_postrun_seconds": self.fan_postrun_seconds,
            "min_run_seconds": self.min_run_seconds,
            "max_run_seconds": self.max_run_seconds,
            "rest_seconds": self.rest_seconds,
        }

    def update_display_metrics(self):
        """Syncs local tracking properties straight to UI text widgets."""
        self.t_min_lbl.setText(f"{self.t_min:.1f} °C")
        self.t_max_lbl.setText(f"{self.t_max:.1f} °C")

    def update_status_from_mqtt(
        self,
        current_state: str,
        is_resting: bool,
        sequence_state: str = "OFF",
        heater_relay_on: bool = False,
        cooler_relay_on: bool = False,
        fan_relay_on: bool = False,
    ):
        """Updates diagnostic fields based on messages coming back from your Pi's hardware daemon."""
        self.system_mode = current_state
        self.is_resting = is_resting
        self._set_relay_indicator(
            self.heater_relay_indicator,
            "Heater",
            heater_relay_on,
            "#8b4513",
        )
        self._set_relay_indicator(
            self.cooler_relay_indicator,
            "Cooler",
            cooler_relay_on,
            "#007aff",
        )
        self._set_relay_indicator(
            self.fan_relay_indicator,
            "Fan",
            fan_relay_on,
            "#808080",
        )

        if is_resting:
            status_text = "System State: Rest period active"
        elif sequence_state == "PREHEAT":
            status_text = "System State: Fan preheat active"
        elif sequence_state == "POSTRUN":
            status_text = "System State: Fan post-run active"
        else:
            status_text = f"System State: Active ({current_state})"
        self.status_lbl.setText(status_text)

        # Dynamic style accent injection based on current run profiles
        if current_state == "HEATING":
            self.status_lbl.setStyleSheet("color: #ff3b30; font-weight: bold;")
        elif current_state == "COOLING":
            self.status_lbl.setStyleSheet("color: #007aff; font-weight: bold;")
        else:
            self.status_lbl.setStyleSheet("color: #777777;")

    def update_climate_telemetry(self, data: dict):
        self._latest_climate_telemetry = data
        temperature = data.get("hvac_temperature")
        if temperature is None:
            temperature = self._average_indoor_temperature(
                data.get("environment_sources", {})
            )
        try:
            self.average_house_temp_lbl.setText(f"{float(temperature):.1f} °C")
        except (TypeError, ValueError):
            self.average_house_temp_lbl.setText("--")

    def _average_indoor_temperature(self, sources):
        if not isinstance(sources, dict):
            return None
        temperatures = [
            self._temperature(source)
            for source_name, source in sources.items()
            if source_name != "Ecowitt" and isinstance(source, dict)
        ]
        temperatures = [value for value in temperatures if value is not None]
        return sum(temperatures) / len(temperatures) if temperatures else None

    @staticmethod
    def _temperature(source):
        for key in ("temperature", "outside_temp", "outdoor_temp", "room_temp"):
            value = source.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
        return None

    def _record_climate_sample(self):
        if self._latest_climate_telemetry is None:
            return

        sources = self._latest_climate_telemetry.get("environment_sources", {})
        indoor_temperatures = {}
        for source_name, source in sources.items():
            if source_name == "Ecowitt" or not isinstance(source, dict):
                continue
            temperature = self._temperature(source)
            if temperature is not None:
                indoor_temperatures[source_name] = temperature

        outdoor_source = sources.get("Ecowitt", {})
        outdoor_temperature = (
            self._temperature(outdoor_source)
            if isinstance(outdoor_source, dict)
            else None
        )
        if not indoor_temperatures and outdoor_temperature is None:
            return

        self.climate_history.add_sample(
            datetime.datetime.now(),
            indoor_temperatures,
            outdoor_temperature,
            self.t_min,
            self.t_max,
            self._latest_climate_telemetry.get("heater_relay_on", False),
            self._latest_climate_telemetry.get("cooler_relay_on", False),
            self._latest_climate_telemetry.get("fan_relay_on", False),
        )
        self.climate_chart.set_samples(self.climate_history.samples)

    def _emit_current_configuration(self):
        """Constructs the canonical JSON packet definition required by your background daemon."""
        payload = self._settings_payload()
        try:
            self.settings_store.save(payload)
        except (OSError, TypeError, ValueError) as error:
            print(f"[HVAC SETTINGS ERROR] Unable to save settings: {error}")
        self.settings_changed.emit(payload)
