from __future__ import annotations

import argparse
import random
from datetime import datetime, timezone
from uuid import uuid4

import httpx

PATIENTS = [f"pat_{10001 + i}" for i in range(6)]


def vital(patient: str, anomaly: bool = False) -> dict:
    payload = {
        "heart_rate": random.gauss(78, 6) if not anomaly else random.uniform(125, 155),
        "spo2": random.gauss(98, 0.8) if not anomaly else random.uniform(86, 91),
        "respiratory_rate": random.gauss(16, 1.5) if not anomaly else random.uniform(26, 34),
        "temperature_c": 36.8,
        "systolic_bp": 118,
        "diastolic_bp": 76,
    }
    return {
        "event_id": f"evt_{uuid4().hex[:12]}",
        "source_id": "monitor_sim",
        "event_type": "patient_vital",
        "patient_id": patient,
        "device_id": "monitor_17",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "schema_version": 1,
        "payload": payload,
        "trace_id": uuid4().hex,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic patient vitals")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--anomaly-rate", type=float, default=0.15)
    args = parser.parse_args()
    headers = {"Authorization": f"Bearer {args.token}"}
    with httpx.Client(base_url=args.url, timeout=10) as client:
        for _ in range(args.count):
            event = vital(random.choice(PATIENTS), anomaly=random.random() < args.anomaly_rate)
            res = client.post("/api/v1/events", json=event, headers=headers)
            print(res.status_code, event["event_id"])


if __name__ == "__main__":
    main()
