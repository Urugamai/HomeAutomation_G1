On a new Raspberry Pi, assuming the repository is installed at
/home/markw/HomeAutomation_G1:
<br>
<br>
<code>
<br>
sudo apt update
<br>
sudo apt install -y python3-pyqt6 python3-paho-mqtt
<br>
cd /home/markw
<br>
git clone https://github.com/Urugamai/HomeAutomation_G1.git
<br>
cd /home/markw/HomeAutomation_G1
<br>
sudo cp controllers/homeautomation-clock.service /etc/systemd/system/
<br>
sudo cp controllers/homeautomation-update.service /etc/systemd/system/
<br>
sudo systemctl daemon-reload
<br>
sudo systemctl enable --now homeautomation-clock.service
</code>
<br>
<br>
Check operation:
<br>
<br>
<code>
systemctl status homeautomation-clock.service<br>
journalctl -u homeautomation-clock.service #-f
</code>
<br>
<br>
The service assumes:<br>
- user markw, <br>
- display :0, and <br>
- /home/markw/.Xauthority.<br>

Adjust those paths in the service file if the new device uses a different
username.

Clock host schedules can be configured in
`config/clock-host-config.yml`. Each top-level key is a device hostname:

```yaml
bathroom-clock:
  turn-on: "0400"
  turn-off: "1000"
  touch-on-duration: 60
```

The display stays on during the scheduled period. Outside that period it
sleeps, and a touch or key press wakes it for the configured number of
minutes.
