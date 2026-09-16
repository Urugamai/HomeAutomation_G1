import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSpinBox,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont


class HvacConfigurationPage(QWidget):
    """
    Touchscreen optimized HVAC input panel.
    Emits a structured JSON signal whenever a setpoint or target bound is updated.
    """
    # Event custom emitter passing target payload structures back to the MQTT driver
    settings_changed = pyqtSignal(dict)

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
        self.system_mode = "OFF"
        self.is_resting = False

        # Central Layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(10)
        self.main_layout.setContentsMargins(15, 15, 15, 15)

        # Build Interactive Temperature Selectors
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self._build_temp_picker("Min Target (Heat)", "t_min"))

        # Add visual separator line
        v_line = QFrame()
        v_line.setFrameShape(QFrame.Shape.VLine)
        v_line.setFrameShadow(QFrame.Shadow.Sunken)
        controls_layout.addWidget(v_line)

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

        # Diagnostics / Status Bar Footer Readout
        self.status_lbl = QLabel("System Status: Idle (OFF) | Interlocks Free")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setFont(QFont("Arial", 11, QFont.Weight.Medium))
        self.status_lbl.setStyleSheet("color: #777777;")
        self.main_layout.addWidget(self.status_lbl)

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
            t_min = float(settings.get("target_min", self.t_min))
            t_max = float(settings.get("target_max", self.t_max))
            min_run = int(settings.get("min_run_seconds", self.min_run_seconds))
            max_run = int(settings.get("max_run_seconds", self.max_run_seconds))
            if t_min >= t_max or min_run > max_run:
                print("[HVAC SETTINGS ERROR] Ignoring invalid retained settings")
                return
            self.t_min = t_min
            self.t_max = t_max
            for target_var in (
                "fan_preheat_seconds",
                "fan_postrun_seconds",
                "min_run_seconds",
                "max_run_seconds",
                "rest_seconds",
            ):
                picker = getattr(self, f"{target_var}_picker")
                value = int(settings.get(target_var, getattr(self, target_var)))
                if picker.minimum() <= value <= picker.maximum():
                    setattr(self, target_var, value)
                    picker.blockSignals(True)
                    picker.setValue(value)
                    picker.blockSignals(False)
            self.update_display_metrics()
        except (TypeError, ValueError) as error:
            print(f"[HVAC SETTINGS ERROR] Ignoring invalid retained settings: {error}")
            return

    def update_display_metrics(self):
        """Syncs local tracking properties straight to UI text widgets."""
        self.t_min_lbl.setText(f"{self.t_min:.1f} °C")
        self.t_max_lbl.setText(f"{self.t_max:.1f} °C")

    def update_status_from_mqtt(
        self,
        current_state: str,
        is_resting: bool,
        sequence_state: str = "OFF",
    ):
        """Updates diagnostic fields based on messages coming back from your Pi's hardware daemon."""
        self.system_mode = current_state
        self.is_resting = is_resting

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

    def _emit_current_configuration(self):
        """Constructs the canonical JSON packet definition required by your background daemon."""
        payload = {
            "target_min": self.t_min,
            "target_max": self.t_max,
            "fan_preheat_seconds": self.fan_preheat_seconds,
            "fan_postrun_seconds": self.fan_postrun_seconds,
            "min_run_seconds": self.min_run_seconds,
            "max_run_seconds": self.max_run_seconds,
            "rest_seconds": self.rest_seconds,
        }
        self.settings_changed.emit(payload)
