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

