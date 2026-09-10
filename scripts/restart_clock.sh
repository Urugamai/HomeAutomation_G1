#!/usr/bin/env bash
set -u

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

services=(
    living_zone.service
#    ecowitt_weather.service
#    bom_weather.service
#    sigen_power.service
#    charger.service
#    blinds.service
#    hvac.service
#    cbus.service
    homeautomation-clock.service
)

failed=0

for service_file in living_zone.service homeautomation-clock.service; do
    source_file="$repo_root/controllers/$service_file"
    if [[ ! -f "$source_file" ]]; then
        echo "MISSING SERVICE FILE: $source_file"
        failed=1
        continue
    fi
    echo "INSTALLING: $service_file"
    if ! sudo install -m 0644 "$source_file" "/etc/systemd/system/$service_file"; then
        echo "FAILED TO INSTALL: $service_file"
        failed=1
    fi
done

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
        echo
        sudo journalctl -u "$service" | tail -n 15
    fi
done

if [[ "$failed" -ne 0 ]]; then
    echo
    echo "One or more services were missing or failed."
    exit 1
fi

echo
echo "All configured Clock and environment services restarted successfully."
