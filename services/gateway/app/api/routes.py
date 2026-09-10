from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import current_user, get_redis, get_settings, rate_limit, require
from app.repositories.gateway_repo import GatewayRepository, _alert_dict
from app.schemas.api import (
    AlertAckResponse,
    EventAccepted,
    EventIngestRequest,
    LoginRequest,
    TokenResponse,
)
from app.simulator import build_scenario_events
from medflow_shared.auth import create_token, verify_password
from medflow_shared.config import Settings
from medflow_shared.errors import ValidationError
from medflow_shared.events import HealthcareEvent
from medflow_shared.metrics import EVENTS_INGESTED
from medflow_shared.orm import UserRow
from medflow_shared.registry import load_registry
from medflow_shared.topics import RAW_EVENTS
from medflow_shared.tracing import new_trace_id
from medflow_shared.validation import parse_event, validate_event

router = APIRouter()


async def db_session(request: Request) -> AsyncSession:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(db_session),
) -> TokenResponse:
    user = await session.scalar(select(UserRow).where(UserRow.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    token = create_token(settings, user.username, user.role)
    return TokenResponse(access_token=token, role=user.role, expires_in_minutes=settings.jwt_expire_minutes)


@router.post("/events", response_model=EventAccepted, status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(
    body: EventIngestRequest,
    request: Request,
    user: dict = Depends(require("events:write")),
    _: None = Depends(rate_limit),
    settings: Settings = Depends(get_settings),
) -> EventAccepted:
    trace_id = body.trace_id or getattr(request.state, "trace_id", None) or new_trace_id()
    raw = body.model_dump()
    raw["trace_id"] = trace_id
    try:
        event = parse_event(raw)
        validate_event(event, settings)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await request.app.state.producer.publish(RAW_EVENTS, event.model_dump(), key=event.partition_key)
    EVENTS_INGESTED.labels(event.event_type.value).inc()
    return EventAccepted(event_id=event.event_id, trace_id=trace_id)


@router.get("/events/{event_id}")
async def get_event(
    event_id: str,
    _: dict = Depends(require("events:read")),
    session: AsyncSession = Depends(db_session),
) -> dict:
    repo = GatewayRepository(session)
    summary = await repo.event_summary(event_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="event not found")
    return summary


@router.get("/events")
async def list_events(
    _: dict = Depends(require("events:read")),
    session: AsyncSession = Depends(db_session),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    repo = GatewayRepository(session)
    rows = await repo.recent_events(limit)
    return {
        "items": [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "patient_id": e.patient_id,
                "status": e.processing_status,
                "timestamp": e.event_timestamp.isoformat(),
                "trace_id": e.trace_id,
            }
            for e in rows
        ]
    }


@router.get("/patients/{patient_id}/insights")
async def patient_insights(
    patient_id: str,
    _: dict = Depends(require("events:read")),
    session: AsyncSession = Depends(db_session),
    severity: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
) -> dict:
    repo = GatewayRepository(session)
    start = datetime.fromisoformat(from_.replace("Z", "+00:00")) if from_ else None
    end = datetime.fromisoformat(to.replace("Z", "+00:00")) if to else None
    return await repo.patient_insights(patient_id, start=start, end=end, severity=severity, limit=limit)


@router.get("/alerts")
async def list_alerts(
    _: dict = Depends(require("alerts:read")),
    session: AsyncSession = Depends(db_session),
    patient_id: str | None = None,
    severity: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    alert_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    repo = GatewayRepository(session)
    rows = await repo.list_alerts(
        patient_id=patient_id,
        severity=severity,
        status=status_filter,
        alert_type=alert_type,
        start=None,
        end=None,
        limit=limit,
    )
    return {"items": [_alert_dict(a) for a in rows]}


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertAckResponse)
async def ack_alert(
    alert_id: str,
    user: dict = Depends(require("alerts:ack")),
    session: AsyncSession = Depends(db_session),
    redis: Redis = Depends(get_redis),
) -> AlertAckResponse:
    repo = GatewayRepository(session)
    alert = await repo.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    await repo.ack_alert(alert, user["sub"])
    await redis.publish(
        "alerts:stream",
        json.dumps({"type": "ALERT_ACKNOWLEDGED", "alert": _alert_dict(alert)}),
    )
    return AlertAckResponse(alert_id=alert.id, status=alert.status.lower())


@router.post("/alerts/{alert_id}/resolve", response_model=AlertAckResponse)
async def resolve_alert(
    alert_id: str,
    user: dict = Depends(require("alerts:resolve")),
    session: AsyncSession = Depends(db_session),
    redis: Redis = Depends(get_redis),
) -> AlertAckResponse:
    repo = GatewayRepository(session)
    alert = await repo.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    await repo.resolve_alert(alert, user["sub"])
    await redis.publish(
        "alerts:stream",
        json.dumps({"type": "ALERT_RESOLVED", "alert": _alert_dict(alert)}),
    )
    return AlertAckResponse(alert_id=alert.id, status="resolved")


@router.get("/overview")
async def overview(
    _: dict = Depends(require("ops:read")),
    session: AsyncSession = Depends(db_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    repo = GatewayRepository(session)
    data = await repo.overview()
    lag = await redis.get("ops:consumer_lag")
    p95 = await redis.get("ops:p95_latency_ms")
    data["consumer_lag"] = int(lag) if lag else 0
    data["p95_processing_latency_ms"] = float(p95) if p95 else None
    return data


@router.get("/models")
async def models(
    _: dict = Depends(require("models:read")),
    session: AsyncSession = Depends(db_session),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> dict:
    repo = GatewayRepository(session)
    stats = await repo.model_stats()
    registry = load_registry(settings.model_registry_path)
    circuits = {}
    for name in registry.models:
        circuits[name] = await redis.hgetall(f"model:circuit:{name}")
    return {"stats": stats, "registry": {k: v.__dict__ for k, v in registry.models.items()}, "circuits": circuits}


@router.get("/dlq")
async def dlq(
    _: dict = Depends(require("dlq:read")),
    session: AsyncSession = Depends(db_session),
) -> dict:
    repo = GatewayRepository(session)
    rows = await repo.list_dlq()
    return {
        "items": [
            {
                "id": r.id,
                "event_id": r.event_id,
                "failure_code": r.failure_code,
                "error": r.error,
                "original_topic": r.original_topic,
                "replayed": r.replayed,
                "payload": r.payload,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/dlq/{dlq_id}/replay")
async def replay_dlq(
    dlq_id: str,
    request: Request,
    _: dict = Depends(require("dlq:replay")),
    session: AsyncSession = Depends(db_session),
) -> dict:
    repo = GatewayRepository(session)
    row = await repo.mark_dlq_replayed(dlq_id)
    if row is None:
        raise HTTPException(status_code=404, detail="dlq record not found")
    if not row.payload:
        raise HTTPException(status_code=400, detail="no payload to replay")
    await request.app.state.producer.publish(RAW_EVENTS, row.payload, key=row.event_id)
    return {"id": row.id, "status": "replayed"}


@router.get("/audit")
async def audit(
    _: dict = Depends(require("audit:read")),
    session: AsyncSession = Depends(db_session),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    repo = GatewayRepository(session)
    rows = await repo.audit(limit)
    return {
        "items": [
            {
                "id": r.id,
                "trace_id": r.trace_id,
                "actor": r.actor,
                "action": r.action,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "metadata": r.metadata_,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/patients")
async def patients(
    _: dict = Depends(require("events:read")),
    session: AsyncSession = Depends(db_session),
) -> dict:
    from medflow_shared.orm import PatientRow

    rows = list((await session.scalars(select(PatientRow).order_by(PatientRow.external_ref))).all())
    return {
        "items": [
            {"id": p.external_ref, "display_name": p.display_name, "ward_id": p.ward_id} for p in rows
        ]
    }


@router.post("/simulator/scenarios/{name}", status_code=status.HTTP_202_ACCEPTED)
async def run_scenario(
    name: str,
    request: Request,
    user: dict = Depends(require("simulator:run")),
    settings: Settings = Depends(get_settings),
    count: int = Query(40, ge=1, le=500),
    patient_id: str | None = None,
) -> dict:
    events = build_scenario_events(name, count=count, patient_id=patient_id)
    if not events:
        raise HTTPException(status_code=404, detail="unknown scenario")
    for event in events:
        try:
            validate_event(HealthcareEvent.model_validate(event), settings)
        except ValidationError:
            # poison / skew scenarios intentionally include invalid events
            pass
        await request.app.state.producer.publish(RAW_EVENTS, event, key=event.get("patient_id") or event["event_id"])
        EVENTS_INGESTED.labels(event["event_type"]).inc()
    return {"scenario": name, "accepted": len(events), "status": "accepted"}


@router.get("/simulator/scenarios")
async def list_scenarios(_: dict = Depends(require("simulator:run"))) -> dict:
    return {
        "items": [
            {"name": "normal_ward", "description": "Steady synthetic vitals within normal ranges"},
            {"name": "deteriorating_patient", "description": "Rising HR, falling SpO2 — expected HIGH alerts"},
            {"name": "duplicate_storm", "description": "Same event_id repeated; tests idempotency"},
            {"name": "bed_crunch", "description": "Ward occupancy climbing toward capacity"},
            {"name": "imaging_backlog", "description": "Long-wait CT/MRI requests for prioritization"},
            {"name": "malformed_poison", "description": "Invalid payloads routed to DLQ"},
            {"name": "clock_skew", "description": "Future timestamps rejected / quarantined"},
        ]
    }


class ConnectionManager:
    def __init__(self) -> None:
        self.clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.clients:
            self.clients.remove(ws)

    async def broadcast(self, message: str) -> None:
        stale = []
        for ws in self.clients:
            try:
                await ws.send_text(message)
            except Exception:  # noqa: BLE001
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


manager = ConnectionManager()


@router.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    token = ws.query_params.get("token")
    settings: Settings = ws.app.state.settings
    if not token:
        await ws.close(code=4401)
        return
    try:
        decode_token_safe(settings, token)
    except ValueError:
        await ws.close(code=4401)
        return
    await manager.connect(ws)
    pubsub = ws.app.state.redis.pubsub()
    await pubsub.subscribe("alerts:stream", "events:stream")
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("data"):
                data = message["data"]
                text = data if isinstance(data, str) else data.decode()
                await ws.send_text(text)
            try:
                incoming = await asyncio.wait_for(ws.receive_text(), timeout=0.1)
                if incoming == "ping":
                    await ws.send_text(json.dumps({"type": "PONG"}))
            except TimeoutError:
                pass
            except WebSocketDisconnect:
                break
    finally:
        manager.disconnect(ws)
        await pubsub.unsubscribe()
        await pubsub.close()


def decode_token_safe(settings: Settings, token: str) -> dict:
    from medflow_shared.auth import decode_token

    return decode_token(settings, token)
