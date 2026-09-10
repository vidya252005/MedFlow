from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from medflow_shared.orm import AlertRow, AuditRow, DecisionRow, DlqRow, EventRow, PatientRow, PredictionRow


class GatewayRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_event(self, event_id: str) -> EventRow | None:
        return await self.session.get(EventRow, event_id)

    async def event_summary(self, event_id: str) -> dict[str, Any] | None:
        event = await self.get_event(event_id)
        if event is None:
            return None
        pred_count = await self.session.scalar(
            select(func.count()).select_from(PredictionRow).where(PredictionRow.event_id == event_id)
        )
        decision = await self.session.scalar(select(DecisionRow).where(DecisionRow.event_id == event_id))
        return {
            "event_id": event.event_id,
            "status": event.processing_status,
            "event_type": event.event_type,
            "patient_id": event.patient_id,
            "timestamp": event.event_timestamp.isoformat(),
            "prediction_count": int(pred_count or 0),
            "decision_id": decision.id if decision else None,
            "severity": decision.severity if decision else None,
            "action": decision.action if decision else None,
            "trace_id": event.trace_id,
            "payload": event.payload,
        }

    async def recent_events(self, limit: int = 50) -> list[EventRow]:
        result = await self.session.scalars(select(EventRow).order_by(EventRow.created_at.desc()).limit(limit))
        return list(result)

    async def patient_insights(
        self,
        patient_id: str,
        *,
        start: datetime | None,
        end: datetime | None,
        severity: str | None,
        limit: int,
    ) -> dict[str, Any]:
        patient = await self.session.scalar(select(PatientRow).where(PatientRow.external_ref == patient_id))
        ev_q = select(EventRow).where(EventRow.patient_id == patient_id).order_by(EventRow.event_timestamp.desc())
        if start:
            ev_q = ev_q.where(EventRow.event_timestamp >= start)
        if end:
            ev_q = ev_q.where(EventRow.event_timestamp <= end)
        events = list((await self.session.scalars(ev_q.limit(limit))).all())
        alerts_q = select(AlertRow).where(AlertRow.patient_id == patient_id).order_by(AlertRow.created_at.desc())
        if severity:
            alerts_q = alerts_q.where(AlertRow.severity == severity)
        alerts = list((await self.session.scalars(alerts_q.limit(limit))).all())
        decisions = list(
            (
                await self.session.scalars(
                    select(DecisionRow).where(DecisionRow.patient_id == patient_id).order_by(DecisionRow.created_at.desc()).limit(limit)
                )
            ).all()
        )
        return {
            "patient": {
                "id": patient_id,
                "display_name": patient.display_name if patient else patient_id,
                "ward_id": patient.ward_id if patient else None,
            },
            "events": [_event_dict(e) for e in events],
            "alerts": [_alert_dict(a) for a in alerts],
            "decisions": [_decision_dict(d) for d in decisions],
        }

    async def list_alerts(
        self,
        *,
        patient_id: str | None,
        severity: str | None,
        status: str | None,
        alert_type: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> list[AlertRow]:
        q = select(AlertRow).order_by(AlertRow.created_at.desc()).limit(limit)
        if patient_id:
            q = q.where(AlertRow.patient_id == patient_id)
        if severity:
            q = q.where(AlertRow.severity == severity)
        if status:
            q = q.where(AlertRow.status == status)
        if alert_type:
            q = q.where(AlertRow.alert_type == alert_type)
        if start:
            q = q.where(AlertRow.created_at >= start)
        if end:
            q = q.where(AlertRow.created_at <= end)
        return list((await self.session.scalars(q)).all())

    async def get_alert(self, alert_id: str) -> AlertRow | None:
        return await self.session.get(AlertRow, alert_id)

    async def ack_alert(self, alert: AlertRow, actor: str) -> AlertRow:
        if alert.status not in {"OPEN", "CREATED"}:
            return alert
        alert.status = "ACKNOWLEDGED"
        alert.acknowledged_at = datetime.now(timezone.utc)
        alert.acknowledged_by = actor
        self.session.add(
            AuditRow(
                trace_id=alert.event_id,
                actor=actor,
                action="ALERT_ACKNOWLEDGED",
                resource_type="alert",
                resource_id=alert.id,
                metadata_={"severity": alert.severity},
            )
        )
        return alert

    async def resolve_alert(self, alert: AlertRow, actor: str) -> AlertRow:
        alert.status = "RESOLVED"
        alert.resolved_at = datetime.now(timezone.utc)
        self.session.add(
            AuditRow(
                trace_id=alert.event_id,
                actor=actor,
                action="ALERT_RESOLVED",
                resource_type="alert",
                resource_id=alert.id,
            )
        )
        return alert

    async def list_dlq(self, limit: int = 50) -> list[DlqRow]:
        return list((await self.session.scalars(select(DlqRow).order_by(DlqRow.created_at.desc()).limit(limit))).all())

    async def mark_dlq_replayed(self, dlq_id: str) -> DlqRow | None:
        row = await self.session.get(DlqRow, dlq_id)
        if row is None:
            return None
        row.replayed = True
        return row

    async def audit(self, limit: int = 100) -> list[AuditRow]:
        return list((await self.session.scalars(select(AuditRow).order_by(AuditRow.created_at.desc()).limit(limit))).all())

    async def overview(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        minute_ago = now - timedelta(minutes=1)
        events_min = await self.session.scalar(
            select(func.count()).select_from(EventRow).where(EventRow.created_at >= minute_ago)
        )
        open_alerts = await self.session.scalar(
            select(func.count()).select_from(AlertRow).where(AlertRow.status.in_(["OPEN", "CREATED"]))
        )
        patients = await self.session.scalar(
            select(func.count(func.distinct(EventRow.patient_id))).where(EventRow.created_at >= now - timedelta(hours=1))
        )
        pred_ok = await self.session.scalar(
            select(func.count()).select_from(PredictionRow).where(PredictionRow.status == "success")
        )
        pred_all = await self.session.scalar(select(func.count()).select_from(PredictionRow))
        success = (float(pred_ok) / float(pred_all)) if pred_all else 1.0
        by_type = await self.session.execute(
            select(AlertRow.severity, func.count()).where(AlertRow.status.in_(["OPEN", "CREATED"])).group_by(AlertRow.severity)
        )
        severity_counts = {row[0]: row[1] for row in by_type.all()}
        return {
            "events_per_min": int(events_min or 0),
            "active_patients": int(patients or 0),
            "open_alerts": int(open_alerts or 0),
            "model_success_rate": round(success, 4),
            "alerts_by_severity": severity_counts,
        }

    async def model_stats(self) -> list[dict[str, Any]]:
        names = await self.session.execute(
            select(PredictionRow.model_name, PredictionRow.model_version).distinct()
        )
        out = []
        for name, version in names.all():
            all_p = list(
                (
                    await self.session.scalars(
                        select(PredictionRow).where(
                            PredictionRow.model_name == name, PredictionRow.model_version == version
                        )
                    )
                ).all()
            )
            if not all_p:
                continue
            latencies = sorted(p.latency_ms or 0 for p in all_p)
            p95 = latencies[int(0.95 * (len(latencies) - 1))] if latencies else 0
            success = sum(1 for p in all_p if p.status == "success") / len(all_p)
            out.append(
                {
                    "model_name": name,
                    "model_version": version,
                    "p95_ms": round(p95, 2),
                    "success_rate": round(success, 4),
                    "count": len(all_p),
                }
            )
        return out


def _event_dict(e: EventRow) -> dict[str, Any]:
    return {
        "event_id": e.event_id,
        "event_type": e.event_type,
        "timestamp": e.event_timestamp.isoformat(),
        "status": e.processing_status,
        "payload": e.payload,
        "trace_id": e.trace_id,
    }


def _alert_dict(a: AlertRow) -> dict[str, Any]:
    return {
        "id": a.id,
        "patient_id": a.patient_id,
        "event_id": a.event_id,
        "alert_type": a.alert_type,
        "severity": a.severity,
        "status": a.status,
        "message": a.message,
        "explanation": a.explanation,
        "created_at": a.created_at.isoformat(),
        "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
    }


def _decision_dict(d: DecisionRow) -> dict[str, Any]:
    return {
        "id": d.id,
        "event_id": d.event_id,
        "severity": d.severity,
        "action": d.action,
        "decision_score": d.decision_score,
        "confidence": d.confidence,
        "triggered_rules": d.triggered_rules,
        "explanation": d.explanation,
        "created_at": d.created_at.isoformat(),
    }
