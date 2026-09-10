from __future__ import annotations

from medflow_shared.events import EventType
from medflow_shared.registry import load_registry
from tests.imports import ROOT, load

router_mod = load("orch_router", "services/orchestrator/app/router.py")


def test_vital_routes_to_anomaly_and_risk() -> None:
    registry = load_registry(str(ROOT / "models" / "registry.yaml"))
    router = router_mod.ModelRouter(registry)
    selected = router.select(EventType.PATIENT_VITAL)
    assert "anomaly_detector" in selected
    assert "risk_predictor" in selected


def test_bed_routes_to_capacity() -> None:
    registry = load_registry(str(ROOT / "models" / "registry.yaml"))
    router = router_mod.ModelRouter(registry)
    selected = router.select(EventType.BED_STATUS)
    assert "capacity_forecaster" in selected


def test_appointment_routes_to_none() -> None:
    registry = load_registry(str(ROOT / "models" / "registry.yaml"))
    router = router_mod.ModelRouter(registry)
    assert router.select(EventType.APPOINTMENT_EVENT) == []
