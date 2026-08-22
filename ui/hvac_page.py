import json
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
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

    def update_display_metrics(self):
        """Syncs local tracking properties straight to UI text widgets."""
        self.t_min_lbl.setText(f"{self.t_min:.1f} °C")
        self.t_max_lbl.setText(f"{self.t_max:.1f} °C")

    def update_status_from_mqtt(self, current_state: str, is_resting: bool):
        """Updates diagnostic fields based on messages coming back from your Pi's hardware daemon."""
        self.system_mode = current_state
        self.is_resting = is_resting

        rest_msg = " [REST PERIOD ACTIVE]" if is_resting else ""
        self.status_lbl.setText(f"System State: Active ({current_state}){rest_msg}")

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
            "target_max": self.t_max
        }
        self.settings_changed.emit(payload)
