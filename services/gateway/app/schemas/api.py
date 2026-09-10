from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from medflow_shared.events import EventType


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    expires_in_minutes: int


class EventIngestRequest(BaseModel):
    event_id: str
    source_id: str
    event_type: EventType
    patient_id: str | None = None
    device_id: str | None = None
    resource_id: str | None = None
    timestamp: str
    schema_version: int = 1
    payload: dict[str, Any]
    trace_id: str | None = None


class EventAccepted(BaseModel):
    event_id: str
    status: str = "accepted"
    trace_id: str


class AlertAckResponse(BaseModel):
    alert_id: str
    status: str


class ScenarioRequest(BaseModel):
    name: str
    events_count: int = Field(default=40, ge=1, le=500)
    patient_id: str | None = None
