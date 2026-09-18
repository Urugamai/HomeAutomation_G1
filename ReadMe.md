On a new Raspberry Pi, assuming the repository is installed at
/home/markw/HomeAutomation_G1:
<br>
<br>
<h1>Initialising commands</h1>
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
<h1>Check operation:</h1>
<br>
<br>
<code>
systemctl status homeautomation-clock.service<br>
journalctl -u homeautomation-clock.service #-f
</code>
<br>
<br>
<h1>Rotate screen</h1>
<h2>option 1:</h2>

```bash
export DISPLAY=:0;
wlr-randr --output HDMI-A-1 --transform 90
```
<br>For older systems use<br>

```bash
xrandr --output HDMI-1 --rotate left
```
<h2>option 2:</h2>

```bash
vi ~/.config/wayfire.ini</code> and add:
```
<code>
<br>[output:HDMI-A-1]
<br>transform = 90
</code>
<h2>option 3:</h2>
as root

```bash
vi /boot/firmware/cmdline.txt
```
KEEP IT AS ONE LINE and append
<code>
<br>
video=HDMI-A-1:400x1280M@59,rotate=90
</code>
<br>
<h2>option 4:</h2>
The Pi Zero WH and 32-bit OS do not change the recommendation
if it is using KMS, and `HDMI-A-1` indicates it likely is.
Use the `video=...rotate=90` kernel argument in
`/boot/firmware/cmdline.txt`.
<br>Otherwise:<br>
Confirm the graphics stack with:

```bash
grep -E 'dtoverlay=.*vc4|display_rotate' /boot/firmware/config.txt
```

- `dtoverlay=vc4-kms-v3d` → use `cmdline.txt` with `video=HDMI-A-1:400x1280M@59,rotate=90`.
- `vc4-fkms-v3d` or no VC4 overlay → use legacy `/boot/firmware/config.txt` instead:

```ini
display_rotate=1
```

Then reboot.
<br>
<h1>The service assumes:</h1>
<li>user markw<br>
<li>display :0<br>
<li>path to Xauthority is: /home/markw/.Xauthority
<br>
Adjust those paths in the service file if the new device uses a different
username.
<br>
<br>
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
<br>
The Status Core power chart samples house consumption every 15 seconds and
stores the current day's readings in
`/mnt/WatsonHome/home_power_history.json` when the NAS mount is available.
