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
