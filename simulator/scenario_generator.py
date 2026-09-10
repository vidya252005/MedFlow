from __future__ import annotations

import argparse
import json

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger named dashboard scenarios via the gateway")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--name", default="deteriorating_patient")
    parser.add_argument("--count", type=int, default=40)
    args = parser.parse_args()
    headers = {"Authorization": f"Bearer {args.token}"}
    with httpx.Client(base_url=args.url, timeout=30) as client:
        res = client.post(
            f"/api/v1/simulator/scenarios/{args.name}",
            params={"count": args.count},
            headers=headers,
        )
        print(res.status_code, json.dumps(res.json(), indent=2))


if __name__ == "__main__":
    main()
