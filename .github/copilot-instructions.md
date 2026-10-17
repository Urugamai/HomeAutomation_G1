# Android companion app

The Android desk controller lives in `C:\Development\DeskControllerAndroid` and talks to the home controller over MQTT.

When a change in this repo touches the MQTT contract, tell the user at the end of the task that the Android app likely needs a matching update, and name the affected Android files. The contract covers:

- Topic names, payload fields, QoS or retain flags for `home/hvac/settings`, `home/hvac/command`, `home/environment/#`, `home/power/sigen`, `home/charger/status` and `home/blinds/command`.
- Validation rules or defaults in `libraries/hvac_settings.py` (HVAC setting keys, ranges, vacation and empty-house fields).
- Telemetry fields built in `libraries/mqtt_engine.py` and the controller daemons (`hvac_state`, `hvac_settings`, relay states, `environment_sources`, charger status).

Android counterparts: `app/src/main/java/com/urugamai/deskcontroller/MqttRepository.kt` (subscribe/publish) and `Telemetry.kt` (payload parsing), plus `TelemetryReducerTest.kt`.
