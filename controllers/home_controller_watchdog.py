import os
import subprocess
import time
from pathlib import Path


HEARTBEAT_PATH = Path("/run/home-controller/heartbeat")
HOME_CONTROLLER_SERVICE = "home_controller.service"
HEARTBEAT_MAX_AGE_SECONDS = 10 * 60
CHECK_INTERVAL_SECONDS = 30


def heartbeat_is_fresh(path=HEARTBEAT_PATH, now=None) -> bool:
    """Returns whether the display event loop has updated its heartbeat recently."""
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except OSError:
        return False
    return max(age, 0) <= HEARTBEAT_MAX_AGE_SECONDS


def home_controller_is_active() -> bool:
    result = subprocess.run(
        ["/usr/bin/systemctl", "is-active", "--quiet", HOME_CONTROLLER_SERVICE],
        check=False,
    )
    return result.returncode == 0


def reboot_system() -> None:
    print("[WATCHDOG] Home controller remained unhealthy for 10 minutes. Rebooting.")
    subprocess.run(["/usr/bin/systemctl", "reboot"], check=False)


def main() -> None:
    unhealthy_since = None

    while True:
        healthy = home_controller_is_active() and heartbeat_is_fresh()
        if healthy:
            unhealthy_since = None
        elif unhealthy_since is None:
            unhealthy_since = time.monotonic()
            print("[WATCHDOG] Home controller heartbeat is unhealthy. Starting 10-minute timer.")
        elif time.monotonic() - unhealthy_since >= HEARTBEAT_MAX_AGE_SECONDS:
            reboot_system()
            return

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
