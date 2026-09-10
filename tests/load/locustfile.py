from locust import HttpUser, between, task
import time
import uuid


class IngestUser(HttpUser):
    wait_time = between(0.01, 0.05)

    def on_start(self):
        res = self.client.post("/api/v1/auth/login", json={"username": "admin", "password": "medflow"})
        self.token = res.json()["access_token"]

    @task
    def ingest(self):
        event_id = f"evt_locust_{uuid.uuid4().hex[:12]}"
        self.client.post(
            "/api/v1/events",
            json={
                "event_id": event_id,
                "source_id": "locust",
                "event_type": "patient_vital",
                "patient_id": "pat_10092",
                "device_id": "monitor_17",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "schema_version": 1,
                "payload": {"heart_rate": 88, "spo2": 96, "respiratory_rate": 18},
                "trace_id": uuid.uuid4().hex,
            },
            headers={"Authorization": f"Bearer {self.token}"},
            name="POST /events",
        )
