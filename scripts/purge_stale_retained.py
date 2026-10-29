"""Clear retained MQTT messages whose payload timestamp is older than N days.

Only retained messages carrying a parseable "timestamp" field are considered;
payloads without one are left alone because their age cannot be determined.

Usage: python scripts/purge_stale_retained.py [--days 10] [--topic home/environment/#] [--dry-run]
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from libraries.paho_compat import create_client


def payload_age_seconds(payload: bytes, now: float) -> float | None:
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    ts = data.get("timestamp")
    if isinstance(ts, bool) or ts is None:
        return None
    if isinstance(ts, (int, float)):
        value = float(ts)
        if value > 1e11:  # milliseconds
            value /= 1000.0
        return now - value
    if isinstance(ts, str):
        try:
            return now - datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def find_stale(messages: dict[str, bytes], max_age_days: float, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    limit = max_age_days * 86400
    stale = []
    for topic, payload in messages.items():
        age = payload_age_seconds(payload, now)
        if age is not None and age > limit:
            stale.append(topic)
    return sorted(stale)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--days", type=float, default=10)
    parser.add_argument("--topic", default="home/environment/#")
    parser.add_argument("--wait", type=float, default=3.0, help="seconds to collect retained messages")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    retained: dict[str, bytes] = {}

    def on_message(client, userdata, msg):
        if msg.retain and msg.payload:
            retained[msg.topic] = msg.payload

    client = create_client()
    client.on_message = on_message
    client.connect(args.broker, args.port, keepalive=30)
    client.subscribe(args.topic)
    client.loop_start()
    time.sleep(args.wait)

    stale = find_stale(retained, args.days)
    for topic in stale:
        print(f"{'[DRY-RUN] would clear' if args.dry_run else 'Clearing'} {topic}")
        if not args.dry_run:
            client.publish(topic, b"", qos=1, retain=True).wait_for_publish(5)
    print(f"{len(stale)} stale of {len(retained)} retained topics under {args.topic}")

    client.loop_stop()
    client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
