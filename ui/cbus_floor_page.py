from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGridLayout, QGroupBox, QLabel, QPushButton, QScrollArea, QSlider,
    QVBoxLayout, QWidget,
)


class CbusFloorPage(QWidget):
    """Touch-friendly C-Bus lighting controls for one floor."""

    def __init__(self, floor, command_callback, parent=None, compact=False):
        super().__init__(parent)
        self.floor = floor
        self.command_callback = command_callback
        self.compact = compact
        self.columns = 6 if compact else 4
        self._buttons = {}
        self._sliders = {}

        layout = QVBoxLayout(self)
        if compact:
            layout.setContentsMargins(3, 3, 3, 3)
            layout.setSpacing(2)
        title = QLabel(f"{floor} Floor C-Bus")
        title.setStyleSheet(
            f"font-size: {'12' if compact else '18'}pt; font-weight: bold;"
        )
        layout.addWidget(title)

        self.status_label = QLabel("Waiting for C-Bus devices...")
        if compact:
            self.status_label.setStyleSheet("font-size: 8pt;")
        layout.addWidget(self.status_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        if compact:
            self.scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self.scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
        self.device_widget = QWidget()
        self.grid = QGridLayout(self.device_widget)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        if compact:
            self.grid.setContentsMargins(1, 1, 1, 1)
            self.grid.setHorizontalSpacing(2)
            self.grid.setVerticalSpacing(2)
        self.scroll.setWidget(self.device_widget)
        layout.addWidget(self.scroll)

    @staticmethod
    def _floor_matches(floor, name):
        normalized = name.strip().upper()
        if floor == "Ground":
            return normalized.startswith(("G_", "OUT_"))
        return normalized.startswith("1_")

    @staticmethod
    def _display_name(name):
        return name.replace("_", " ").strip() or "Unnamed C-Bus device"

    def _clear_devices(self):
        self._buttons.clear()
        self._sliders.clear()
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def refresh_devices(self, devices):
        visible = [
            device for device in devices.values()
            if self._floor_matches(self.floor, device.get("name", ""))
        ]
        visible.sort(key=lambda item: item.get("name", "").lower())
        visible_addresses = {device["address"] for device in visible}
        if visible_addresses == set(self._buttons):
            if not visible:
                self.status_label.setText(
                    f"No {self.floor.lower()}-floor C-Bus devices found"
                )
            for device in visible:
                self._update_device(device)
            return

        self._clear_devices()

        for index, device in enumerate(visible):
            address = device["address"]
            group = QGroupBox(self._display_name(device.get("name", "")))
            group_layout = QVBoxLayout(group)
            if self.compact:
                group.setFixedHeight(42)
                group.setStyleSheet(
                    "QGroupBox { font-size: 7pt; margin-top: 10px; "
                    "padding: 0px; }"
                )
                group_layout.setContentsMargins(2, 1, 2, 1)
                group_layout.setSpacing(0)

            button = QPushButton()
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked, group_address=address:
                self._set_state(group_address, checked)
            )
            self._buttons[address] = button
            if self.compact:
                button.setFixedHeight(22)
                button.setStyleSheet("font-size: 8pt;")
            group_layout.addWidget(button)

            if not self.compact:
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(0, 255)
                slider.valueChanged.connect(
                    lambda value, group_address=address:
                    self._set_brightness(group_address, value)
                )
                self._sliders[address] = slider
                group_layout.addWidget(slider)
            self._update_device(device)

            row, column = divmod(index, self.columns)
            self.grid.addWidget(group, row, column)

        self.status_label.setText(
            f"{len(visible)} {self.floor.lower()}-floor C-Bus devices"
            if visible else f"No {self.floor.lower()}-floor C-Bus devices found"
        )

    def _set_state(self, address, checked):
        self.command_callback(address, checked, 255 if checked else 0)

    def _set_brightness(self, address, value):
        if value > 0:
            button = self._buttons.get(address)
            if button and not button.isChecked():
                button.blockSignals(True)
                button.setChecked(True)
                button.blockSignals(False)
        self.command_callback(address, value > 0, value)

    def _update_device(self, device):
        address = device.get("address")
        button = self._buttons.get(address)
        slider = self._sliders.get(address)
        if button is None:
            return
        brightness = max(0, min(255, int(device.get("brightness", 0))))
        is_on = str(device.get("state", "OFF")).upper() == "ON" and brightness > 0
        button.blockSignals(True)
        button.setChecked(is_on)
        button.setText("ON" if is_on else "OFF")
        button.blockSignals(False)
        if slider is not None:
            slider.blockSignals(True)
            slider.setValue(brightness)
            slider.blockSignals(False)
        font_style = "font-size: 8pt; " if self.compact else ""
        button.setStyleSheet(
            "QPushButton:checked { background: #28a745; color: white; "
            f"font-weight: bold; {font_style}}}"
        )

    def update_device(self, device):
        if device.get("address") in self._buttons:
            self._update_device(device)
