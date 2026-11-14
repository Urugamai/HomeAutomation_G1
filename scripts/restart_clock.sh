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

# Watchdog: reboot if the clock heartbeat is not refreshed for 30 seconds.
# The managed block is replaced on every run, so it never accumulates.
watchdog_conf=/etc/watchdog.conf
check_script=/usr/local/bin/clock_heartbeat_check.sh
begin_marker="# BEGIN homeautomation-clock heartbeat"
end_marker="# END homeautomation-clock heartbeat"

echo "INSTALLING: clock_heartbeat_check.sh"
if ! sudo install -m 0755 "$script_dir/clock_heartbeat_check.sh" "$check_script"; then
    echo "FAILED TO INSTALL: clock_heartbeat_check.sh"
    failed=1
elif [[ ! -f "$watchdog_conf" ]]; then
    echo "MISSING: $watchdog_conf (install the 'watchdog' package)"
    failed=1
else
    new_conf="$(mktemp)"
    sudo sed "/^${begin_marker}\$/,/^${end_marker}\$/d" "$watchdog_conf" > "$new_conf"
    {
        echo "$begin_marker"
        echo "test-binary = $check_script"
        echo "test-timeout = 10"
        echo "$end_marker"
    } >> "$new_conf"

    if sudo cmp -s "$new_conf" "$watchdog_conf"; then
        echo "WATCHDOG CONFIG UNCHANGED"
    else
        [[ -f "$watchdog_conf.orig" ]] || sudo cp -p "$watchdog_conf" "$watchdog_conf.orig"
        if sudo install -m 0644 "$new_conf" "$watchdog_conf"; then
            echo "WATCHDOG CONFIG UPDATED"
            sudo systemctl enable watchdog >/dev/null 2>&1
            sudo systemctl restart watchdog || { echo "FAILED TO RESTART: watchdog"; failed=1; }
        else
            echo "FAILED TO UPDATE: $watchdog_conf"
            failed=1
        fi
    fi
    rm -f "$new_conf"
fi

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
