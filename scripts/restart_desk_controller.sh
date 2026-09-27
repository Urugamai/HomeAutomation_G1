#!/usr/bin/env bash
set -u

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
service="desk_controller.service"
source_file="$repo_root/controllers/$service"

if [[ ! -f "$source_file" ]]; then
    echo "MISSING SERVICE FILE: $source_file"
    exit 1
fi

echo "INSTALLING: $service"
if ! sudo install -m 0644 "$source_file" "/etc/systemd/system/$service"; then
    echo "FAILED TO INSTALL: $service"
    exit 1
fi

sudo systemctl daemon-reload

echo "ENABLING: $service"
if ! sudo systemctl enable "$service" >/dev/null; then
    echo "FAILED TO ENABLE: $service"
    exit 1
fi

echo "RESTARTING: $service"
if ! sudo systemctl restart "$service"; then
    echo "FAILED TO RESTART: $service"
    exit 1
fi

echo
echo "SERVICE STATUS"
sudo systemctl --no-pager --full --plain status "$service" | sed -n '1,4p'

echo
echo "SERVICE LOG"
sudo journalctl --no-pager -u "$service" -n 15

echo
echo "Desktop controller restarted successfully."
