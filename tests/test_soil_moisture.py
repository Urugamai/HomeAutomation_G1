import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from libraries.soil_moisture import (
    AMBER, GREEN, RED, battery_color, moisture_color, soil_sensors,
)
from libraries.soil_names import load_soil_names
from ui.soil_moisture_page import SoilMoisturePage


def test_moisture_colour_thresholds():
    assert moisture_color(50) == GREEN
    assert moisture_color(30) == GREEN
    assert moisture_color(70) == GREEN
    assert moisture_color(29.9) == AMBER
    assert moisture_color(70.1) == AMBER
    assert moisture_color(15) == AMBER
    assert moisture_color(90) == AMBER
    assert moisture_color(14.9) == RED
    assert moisture_color(90.1) == RED


def test_battery_colour_thresholds():
    assert battery_color(1.5) == GREEN
    assert battery_color(1.2) == RED
    assert battery_color(15) == RED
    assert battery_color(80) == GREEN


def test_soil_sensors_groups_channels_in_order():
    sensors = soil_sensors({
        "soil_moisture_ch10": 5, "soil_moisture_ch2": 40,
        "soil_battery_ch2": 1.4, "temperature": 20,
    })
    assert sensors == [(2, 40.0, 1.4, "Soil 2"), (10, 5.0, None, "Soil 10")]


def test_soil_sensor_names_come_from_payload():
    sensors = soil_sensors({"soil_moisture_ch1": 40, "soil_name_ch1": "Rose bed"})
    assert sensors == [(1, 40.0, None, "Rose bed")]


def test_soil_names_loaded_from_yaml(tmp_path):
    config = tmp_path / "soil.yml"
    config.write_text("channels:\n  1: Front lawn\n  '2': Veggies\n  x: bad\n  3:\n")
    assert load_soil_names(str(config)) == {1: "Front lawn", 2: "Veggies"}
    assert load_soil_names(str(tmp_path / "missing.yml")) == {}


def test_page_builds_one_widget_per_sensor():
    app = QApplication.instance() or QApplication([])
    page = SoilMoisturePage()
    page.refresh_sources({"Ecowitt": {"soil_moisture_ch1": 45, "soil_battery_ch1": 1.5,
                                      "soil_moisture_ch2": 20}})
    assert sorted(page._widgets) == [1, 2]
    page.refresh_sources({"Ecowitt": {"soil_moisture_ch2": 20}})
    assert sorted(page._widgets) == [2]
    assert app is not None
