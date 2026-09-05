# Configuring environment
#########################
# Update the system package repository index lists
sudo apt update

# Install PyQt6 and the physical system I2C bus tools natively
sudo apt install -y python3-pyqt6 python3-smbus2 python3-pip

# Install the remaining purely Pythonic driver dependencies from your manifest
pip3 install paho-mqtt pymodbus aiohttp pycryptodome --break-system-packages

## DAEMONS ##
# SOURCE UPDATE
# Install and enable the boot-time fast-forward-only source update first.
sudo cp /home/markw/HomeAutomation_G1/controllers/homeautomation-update.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable homeautomation-update.service

# HVAC DAEMON
# Reload the systemd controller manager configuration files
sudo systemctl daemon-reload

# Enable the service file so it launches automatically on boot
sudo systemctl enable hvac.service

# Start the background daemon immediately without restarting the Pi
sudo systemctl start hvac.service

# Check the live system logs to verify the engine is monitoring things correctly
sudo journalctl -u hvac.service -f -n 20

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
sudo systemctl daemon-reload
sudo systemctl enable living_zone.service
sudo systemctl start living_zone.service


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

# START THE DISPLAY
python3 main.py
