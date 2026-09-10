import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.BASE_URL || "http://localhost:8000";

export const options = {
  vus: 20,
  duration: "2m",
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<100"],
  },
};

export function setup() {
  const res = http.post(
    `${BASE}/api/v1/auth/login`,
    JSON.stringify({ username: "admin", password: "medflow" }),
    { headers: { "Content-Type": "application/json" } },
  );
  return { token: res.json("access_token") };
}

export default function (data) {
  const id = `evt_k6_${__VU}_${__ITER}_${Date.now()}`;
  const payload = {
    event_id: id,
    source_id: "k6",
    event_type: "patient_vital",
    patient_id: `pat_${10001 + (__VU % 5)}`,
    device_id: "monitor_k6",
    timestamp: new Date().toISOString(),
    schema_version: 1,
    payload: {
      heart_rate: 70 + (__ITER % 40),
      spo2: 97,
      respiratory_rate: 16,
    },
    trace_id: (`k6${__VU}${__ITER}` + "0000000000000000").slice(0, 16),
  };
  const res = http.post(`${BASE}/api/v1/events`, JSON.stringify(payload), {
    headers: {
      Authorization: `Bearer ${data.token}`,
      "Content-Type": "application/json",
    },
  });
  check(res, { accepted: (r) => r.status === 202 });
  sleep(0.02);
}
