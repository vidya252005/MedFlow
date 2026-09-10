from medflow_shared.events import HealthcareEvent, Prediction, Decision, AlertMessage, FeatureVector, EventType


def test_event_schema_roundtrip() -> None:
    raw = {
        "event_id": "evt_contract_1",
        "source_id": "src",
        "event_type": "patient_vital",
        "patient_id": "pat_1",
        "timestamp": "2026-09-10T08:41:32+00:00",
        "schema_version": 1,
        "payload": {"heart_rate": 80, "spo2": 98, "respiratory_rate": 16},
        "trace_id": "tracecontract01",
    }
    event = HealthcareEvent.model_validate(raw)
    again = HealthcareEvent.model_validate(event.model_dump())
    assert again.event_id == event.event_id
    assert again.event_type == EventType.PATIENT_VITAL


def test_prediction_and_decision_contract() -> None:
    pred = Prediction(model_name="anomaly_detector", model_version="2.1", score=0.2, status="success")
    decision = Decision(
        event_id="evt_1",
        patient_id="pat_1",
        severity="LOW",
        action="MONITOR",
        decision_score=0.1,
        confidence=0.5,
        triggered_rules=[],
        predictions=[pred],
        trace_id="tracecontract01",
    )
    alert = AlertMessage(
        alert_id="al_1",
        event_id="evt_1",
        patient_id="pat_1",
        alert_type="MONITOR",
        severity="LOW",
        status="OPEN",
        message="ok",
        trace_id="tracecontract01",
    )
    FeatureVector.model_validate(
        {
            "event_id": "evt_1",
            "patient_id": "pat_1",
            "event_type": "patient_vital",
            "event_time": "2026-09-10T08:41:32+00:00",
            "trace_id": "tracecontract01",
            "features": {"heart_rate": 80},
            "window_sizes": {"5m": 1},
        }
    )
    assert decision.severity == "LOW"
    assert alert.status == "OPEN"
