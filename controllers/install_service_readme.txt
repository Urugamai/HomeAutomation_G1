# Configuring environment
#########################
# Update the system package repository index lists
sudo apt update

# Install PyQt6, the physical I2C bus tools, and Waveshare relay GPIO support.
sudo apt install -y python3-pyqt6 python3-smbus2 python3-rpi.gpio python3-pip

# Install the remaining purely Pythonic driver dependencies from your manifest
pip3 install paho-mqtt pymodbus aiohttp pycryptodome bme680 --break-system-packages

## DAEMONS ##
# SOURCE UPDATE
# Install and enable the boot-time fast-forward-only source update first.
sudo cp /home/markw/HomeAutomation_G1/controllers/homeautomation-update.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable homeautomation-update.service

# BOM DAEMON
sudo systemctl daemon-reload
sudo systemctl enable bom_weather.service
sudo systemctl start bom_weather.service

# BLINDS DAEMON
# Refresh system folders to read the new unit descriptor profiles
sudo systemctl daemon-reload

# Configure both background files to launch automatically on system boot
sudo systemctl enable charger.service
sudo systemctl enable blinds.service

# CHARGER DAEMON
# Activate the daemons right away without restarting the server
sudo systemctl start charger.service
sudo systemctl start blinds.service

# Verify the live background execution metrics
sudo journalctl -u charger.service -f -n 15

# SIGEN DAEMON
sudo systemctl daemon-reload
sudo systemctl enable sigen_power.service
sudo systemctl start sigen_power.service

# ECOWITT WEATHER
sudo systemctl daemon-reload
sudo systemctl enable ecowitt_weather.service
sudo systemctl start ecowitt_weather.service

# HVAC as LIVING ZONE
# The restart_clock.sh and restart_home_controller.sh scripts install this
# unit automatically on new devices before enabling it.
sudo systemctl daemon-reload
sudo systemctl enable living_zone.service
sudo systemctl start living_zone.service

# HVAC RELAY CONTROLLER
# Runs alongside living_zone.service, which publishes sensor telemetry.
sudo cp /home/markw/HomeAutomation_G1/controllers/hvac.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable hvac.service
sudo systemctl start hvac.service

# HOME CONTROLLER DISPLAY
sudo cp /home/markw/HomeAutomation_G1/controllers/home_controller.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable home_controller.service
sudo systemctl start home_controller.service

# HOME CONTROLLER WATCHDOG AND REBOOT CONTROL
sudo cp /home/markw/HomeAutomation_G1/controllers/home_controller_watchdog.service /etc/systemd/system/
sudo visudo -cf /home/markw/HomeAutomation_G1/controllers/home_controller_reboot.sudoers
sudo cp /home/markw/HomeAutomation_G1/controllers/home_controller_reboot.sudoers /etc/sudoers.d/home_controller_reboot
sudo chmod 0440 /etc/sudoers.d/home_controller_reboot
sudo systemctl daemon-reload
sudo systemctl enable --now home_controller_watchdog.service

# Verify the display controller logs
sudo journalctl -u home_controller.service -f -n 20


# Start all daemons
#####################
# 1. Start the local Living Area I2C sensors and Waveshare HVAC relay driver (Requires sudo for GPIO/I2C)
sudo python3 controllers/environment_daemon.py > ~/living_zone.log 2>&1 &

# 2. Start the Ecowitt LAN socket listener to pull Rumpus Room and outdoor metrics
python3 controllers/ecowitt_daemon.py > ~/ecowitt.log 2>&1 &

# 3. Start the SigenStor async inverter web crawler
python3 controllers/sigen_daemon.py > ~/sigen.log 2>&1 &

# 4. Start the Bureau of Meteorology hourly XML forecast sync downloader
python3 controllers/bom_daemon.py > ~/bom.log 2>&1 &

# The display is managed by home_controller.service.
