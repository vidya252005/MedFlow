from __future__ import annotations

import argparse
from datetime import datetime, timezone
from uuid import uuid4

import httpx


def reading(device_id: str, patient_id: str) -> dict:
    return {
        "event_id": f"evt_{uuid4().hex[:12]}",
        "source_id": device_id,
        "event_type": "device_reading",
        "patient_id": patient_id,
        "device_id": device_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "schema_version": 1,
        "payload": {"metric": "spo2", "value": 97.4, "unit": "%", "quality": "good"},
        "trace_id": uuid4().hex,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()
    headers = {"Authorization": f"Bearer {args.token}"}
    with httpx.Client(base_url=args.url, timeout=10) as client:
        for i in range(args.count):
            event = reading(f"monitor_{i % 5}", "pat_10092")
            print(client.post("/api/v1/events", json=event, headers=headers).status_code)


if __name__ == "__main__":
    main()
