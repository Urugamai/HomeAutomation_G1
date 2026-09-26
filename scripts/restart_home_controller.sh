#!/usr/bin/env bash
set -u

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

services=(
    living_zone.service
    ecowitt_weather.service
    bom_weather.service
    sigen_power.service
    charger.service
    cbus_command_dispatcher.service
    blinds.service
    hvac.service
    home_controller.service
    home_controller_watchdog.service
#    cbus.service
)

failed=0

for service in living_zone.service hvac.service home_controller.service home_controller_watchdog.service cbus_command_dispatcher.service; do
    source_file="$repo_root/controllers/$service"
    if [[ ! -f "$source_file" ]]; then
        echo "MISSING SERVICE FILE: $source_file"
        failed=1
        continue
    fi

    echo "INSTALLING: $service"
    if ! sudo install -m 0644 "$source_file" "/etc/systemd/system/$service"; then
        echo "FAILED TO INSTALL: $service"
        failed=1
    fi
done

sudoers_file="$repo_root/controllers/home_controller_reboot.sudoers"
if ! sudo visudo -cf "$sudoers_file"; then
    echo "INVALID SUDOERS FILE: $sudoers_file"
    failed=1
else
    echo "INSTALLING: home_controller_reboot.sudoers"
    if ! sudo install -m 0440 "$sudoers_file" /etc/sudoers.d/home_controller_reboot; then
        echo "FAILED TO INSTALL: home_controller_reboot.sudoers"
        failed=1
    fi
fi

sudo systemctl daemon-reload

for service in "${services[@]}"; do
    if ! sudo systemctl cat "$service" >/dev/null 2>&1; then
        echo "MISSING: $service"
        failed=1
        continue
    fi

    echo "ENABLING: $service"
    if ! sudo systemctl enable "$service" >/dev/null; then
        echo "FAILED TO ENABLE: $service"
        failed=1
        continue
    fi

    echo "RESTARTING: $service"
    if ! sudo systemctl restart "$service"; then
        echo "FAILED TO RESTART: $service"
        failed=1
    fi
done

echo
echo "SERVICE STATUS"
for service in "${services[@]}"; do
    if sudo systemctl cat "$service" >/dev/null 2>&1; then
        sudo systemctl --no-pager --full --plain status "$service" | \
            sed -n '1,4p'
    fi
done

echo "SERVICE LOG"
for service in "${services[@]}"; do
    if sudo systemctl cat "$service" >/dev/null 2>&1; then
        sudo journalctl -u "$service" | tail -n 15
    fi
done

if [[ "$failed" -ne 0 ]]; then
    echo
    echo "One or more services were missing or failed."
    exit 1
fi

echo
echo "All configured Home Automation services restarted successfully."
