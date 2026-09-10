# MedFlow

Real-time **synthetic** healthcare event orchestration. Not a clinical product, medical device, or diagnostic system.

MedFlow ingests patient/device/resource events, processes them asynchronously over Kafka, runs multiple AI models in parallel with isolation, applies deterministic rules, and pushes insights to a live dashboard.

The interesting part is not the models. It is the platform around them: idempotency, backpressure, timeouts, circuit breakers, dead-letter handling, tracing, and measurable latency.

> This repository is a software-engineering prototype using **synthetic healthcare data only**. It is not intended for clinical use.

---

## What it demonstrates

| Area | How it shows up |
| --- | --- |
| Event-driven design | Kafka topics per stage, 202 Accepted at the edge |
| Concurrency | Parallel model inference, bounded worker pools, Redis `SETNX` races |
| Reliability | Per-model timeouts, retries with jitter, circuit breakers, DLQ + replay |
| Data | PostgreSQL as durable store, Redis for hot state, outbox row on alert create |
| AI as a component | Registry + router + `AIModel` adapter; rules stay deterministic |
| Observability | JSON logs with `trace_id`, Prometheus metrics, Grafana, live WebSocket |
| Security | JWT + RBAC, rate limits, validation, audit log, no secrets in logs |

---

## Architecture

```text
Client / Simulator / Dashboard
              |
              | POST /api/v1/events   →  202 Accepted
              v
         API Gateway (auth, rate limit, schema)
              |
              v
            Kafka
              |
     raw → ingestion → validated → features → predictions → decisions → alerts
              |                         |            |            |
           Postgres                  Redis      sklearn /      rules
           idempotency               windows    heuristics     engine
                                                            |
                                                            v
                                              Alert service → Redis pub/sub
                                                            |
                                                            v
                                              WebSocket dashboard
```

Topics:

`healthcare.events.raw` · `validated` · `features.ready` · `predictions` · `decisions` · `alerts` · `audit` · `events.dlq`

Patient events are partitioned by `patient_id` so ordering holds **within** a patient while unrelated patients run concurrently. Delivery is **at-least-once**; consumers are idempotent. That is the realistic guarantee, not end-to-end exactly-once.

---

## Extra capabilities beyond the original LLD

- **Explainability payload** on every decision (features, rule reasons, model scores, shadow models).
- **Shadow inference** (`anomaly_detector_shadow`) recorded but excluded from alerting.
- **DLQ browser + replay** from the dashboard.
- **Named scenario simulator** (deteriorating patient, duplicate storm, bed crunch, imaging backlog, poison messages, clock skew).
- **Data-quality model** and imaging prioritization, not only vitals.
- **Model ops panel**: circuit state, p95, success rate.
- **Patient timeline** of events / decisions / alerts.
- **Alert state machine** with acknowledge / resolve and audit entries.

Safer output vocabulary on purpose: `ANOMALY_DETECTED`, `RESOURCE_CONGESTION`, `DATA_QUALITY_ISSUE`, `MODEL_CONFIDENCE_LOW`, `REVIEW_RECOMMENDED`. The system never diagnoses or prescribes.

---

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

| Surface | URL |
| --- | --- |
| Dashboard | http://localhost:3000 |
| Gateway OpenAPI | http://localhost:8000/docs |
| Prometheus | http://localhost:9090 |
| Grafana (admin / medflow) | http://localhost:3001 |

Demo users (password `medflow`): `admin`, `analyst`, `viewer`.

1. Sign in as `admin`.
2. Run **deteriorating_patient**.
3. Watch the live stream and Alerts tab.
4. Run **duplicate_storm** — one decision, the rest suppressed.
5. Run **malformed_poison** — Dead letters tab.

---

## Local tests

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt -e shared
pytest -q
```

Frontend:

```bash
cd frontend && npm install && npm run dev
```

Load (gateway must be up):

```bash
k6 run tests/load/k6_ingest.js
# or
locust -f tests/load/locustfile.py --host http://localhost:8000
```

---

## API sketch

`POST /api/v1/events` returns **202** because ingestion acknowledgement is not inference completion.

```http
POST /api/v1/events
Authorization: Bearer <token>
```

```json
{
  "event_id": "evt_123",
  "source_id": "monitor_17",
  "event_type": "patient_vital",
  "patient_id": "pat_101",
  "timestamp": "2026-09-10T08:41:32Z",
  "schema_version": 1,
  "payload": { "heart_rate": 128, "spo2": 91, "respiratory_rate": 27 }
}
```

Also: login, event lookup, patient insights, alerts ack/resolve, models, DLQ replay, audit, WebSocket `/api/v1/stream?token=`.

---

## Engineering targets (project SLOs, not clinical claims)

| Target | Value |
| --- | --- |
| Ingest ack p95 | < 100 ms |
| End-to-end processing p95 | < 500 ms |
| Duplicate decisions | 0 (idempotent consumers) |
| Model timeout | per-model in `models/registry.yaml` |

Measure after you run k6/Locust; put the real numbers in a résumé bullet. Empty `X events/sec` claims are worse than no claim.

Suggested experiments (see LLD §102): throughput sweep, worker scaling, sequential vs parallel inference, Redis on/off, model outage + circuit open, 1,000 duplicate event IDs.

---

## Repository map

```text
services/gateway            JWT, REST, WebSocket, simulator
services/ingestion          validate, dedup, persist, DLQ
services/feature-service    sliding windows + feature cache
services/orchestrator       router, parallel inference, CB
services/rules-engine       deterministic policies + aggregation
services/alert-service      alert lifecycle + Redis fanout
shared/medflow_shared       events, auth, kafka, redis, metrics
models/registry.yaml        versions, routing, weights
frontend                    React operations UI
simulator/                  CLI producers
deployment/                 Docker, Prometheus, Grafana
tests/                      unit + k6/locust
```
---

## License / disclaimer

Synthetic data. No PHI. No clinical validity. Built as a portfolio systems project.
