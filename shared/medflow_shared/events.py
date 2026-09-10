from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventType(str, Enum):
    PATIENT_VITAL = "patient_vital"
    DEVICE_READING = "device_reading"
    BED_STATUS = "bed_status"
    IMAGING_REQUEST = "imaging_request"
    LAB_RESULT = "lab_result"
    RESOURCE_UPDATE = "resource_update"
    APPOINTMENT_EVENT = "appointment_event"


class VitalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heart_rate: float | None = Field(default=None, ge=0, le=300)
    spo2: float | None = Field(default=None, ge=0, le=100)
    respiratory_rate: float | None = Field(default=None, ge=0, le=80)
    temperature_c: float | None = Field(default=None, ge=30, le=45)
    systolic_bp: float | None = Field(default=None, ge=40, le=300)
    diastolic_bp: float | None = Field(default=None, ge=20, le=200)


class DeviceReadingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    value: float
    unit: str | None = None
    quality: Literal["good", "poor", "unknown"] = "good"


class BedStatusPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ward_id: str
    bed_id: str
    status: Literal["available", "occupied", "cleaning", "blocked"]
    occupancy_ratio: float | None = Field(default=None, ge=0, le=1)


class ImagingRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modality: Literal["CT", "MRI", "XRAY", "US", "PET"]
    body_part: str
    waiting_minutes: int = Field(ge=0, le=10_000)
    acuity_hint: Literal["low", "medium", "high"] | None = None


class LabResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_code: str
    value: float
    unit: str
    abnormal_flag: bool = False


class ResourceUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: Literal["staff", "room", "equipment"]
    resource_id: str
    available: int = Field(ge=0)
    capacity: int = Field(ge=0)


class AppointmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    appointment_id: str
    status: Literal["scheduled", "arrived", "in_progress", "completed", "no_show"]
    department: str
    wait_minutes: int = Field(default=0, ge=0)


Payload = Annotated[
    Union[
        VitalPayload,
        DeviceReadingPayload,
        BedStatusPayload,
        ImagingRequestPayload,
        LabResultPayload,
        ResourceUpdatePayload,
        AppointmentPayload,
    ],
    Field(discriminator=None),
]

PAYLOAD_BY_TYPE: dict[EventType, type[BaseModel]] = {
    EventType.PATIENT_VITAL: VitalPayload,
    EventType.DEVICE_READING: DeviceReadingPayload,
    EventType.BED_STATUS: BedStatusPayload,
    EventType.IMAGING_REQUEST: ImagingRequestPayload,
    EventType.LAB_RESULT: LabResultPayload,
    EventType.RESOURCE_UPDATE: ResourceUpdatePayload,
    EventType.APPOINTMENT_EVENT: AppointmentPayload,
}


class HealthcareEvent(BaseModel):
    """Immutable ingested event. Downstream services must not mutate it."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=3, max_length=64)
    source_id: str = Field(min_length=1, max_length=100)
    event_type: EventType
    patient_id: str | None = None
    device_id: str | None = None
    resource_id: str | None = None
    timestamp: str
    schema_version: int = Field(ge=1, le=2)
    payload: dict[str, Any]
    trace_id: str = Field(min_length=8, max_length=64)

    @field_validator("event_id", "source_id", "trace_id")
    @classmethod
    def strip_ids(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("id fields cannot be blank")
        return cleaned

    @property
    def dedup_key(self) -> str:
        return f"{self.event_id}:{self.source_id}"

    @property
    def partition_key(self) -> str:
        return self.patient_id or self.resource_id or self.source_id or self.event_id

    def typed_payload(self) -> BaseModel:
        model = PAYLOAD_BY_TYPE[self.event_type]
        return model.model_validate(self.payload)


class CanonicalEvent(BaseModel):
    """Internal normalized event used after schema versioning."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    patient_id: str | None
    device_id: str | None
    resource_id: str | None
    event_type: EventType
    event_time: str
    source: str
    schema_version: int
    attributes: dict[str, Any]
    trace_id: str

    @classmethod
    def from_healthcare_event(cls, event: HealthcareEvent) -> CanonicalEvent:
        payload = event.typed_payload().model_dump()
        return cls(
            event_id=event.event_id,
            patient_id=event.patient_id,
            device_id=event.device_id,
            resource_id=event.resource_id,
            event_type=event.event_type,
            event_time=event.timestamp,
            source=event.source_id,
            schema_version=event.schema_version,
            attributes=payload,
            trace_id=event.trace_id,
        )


class FeatureVector(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    patient_id: str | None
    event_type: EventType
    event_time: str
    trace_id: str
    features: dict[str, float | int | str | bool | None]
    window_sizes: dict[str, int]
    stale: bool = False
    insufficient_observations: bool = False


class Prediction(BaseModel):
    model_name: str
    model_version: str
    model_hash: str | None = None
    score: float | None = None
    label: str | None = None
    confidence: float | None = None
    latency_ms: float = 0.0
    status: Literal["success", "timeout", "error", "skipped", "fallback", "circuit_open", "shadow"] = "success"
    shadow: bool = False
    explanation: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    event_id: str
    patient_id: str | None
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    action: str
    decision_score: float
    confidence: float
    triggered_rules: list[str]
    predictions: list[Prediction]
    explanation: dict[str, Any] = Field(default_factory=dict)
    trace_id: str


class AlertMessage(BaseModel):
    alert_id: str
    event_id: str
    patient_id: str | None
    alert_type: str
    severity: str
    status: str
    message: str
    explanation: dict[str, Any] = Field(default_factory=dict)
    trace_id: str


class DlqRecord(BaseModel):
    original_topic: str
    event_id: str | None
    failure_code: str
    error: str
    payload: dict[str, Any] | None = None
    partition: int | None = None
    offset: int | None = None
