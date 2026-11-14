#!/usr/bin/env bash
# Used as a watchdog "test-binary": exit 0 = healthy, non-zero = reboot.
heartbeat_file="${1:-/run/homeautomation-clock/heartbeat}"
max_age="${2:-30}"
boot_grace="${3:-180}"

uptime_seconds="$(cut -d. -f1 /proc/uptime)"
if (( uptime_seconds < boot_grace )); then
    exit 0
fi

if [[ ! -f "$heartbeat_file" ]]; then
    echo "clock heartbeat file missing: $heartbeat_file"
    exit 1
fi

age=$(( $(date +%s) - $(stat -c %Y "$heartbeat_file") ))
if (( age > max_age )); then
    echo "clock heartbeat stale: ${age}s old (limit ${max_age}s)"
    exit 1
fi
exit 0
