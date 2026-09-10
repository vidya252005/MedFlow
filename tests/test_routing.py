from __future__ import annotations

import sys
from pathlib import Path

from medflow_shared.events import EventType
from medflow_shared.registry import load_registry

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "orchestrator"))

from app.router import ModelRouter  # noqa: E402


def test_vital_routes_to_anomaly_and_risk() -> None:
    registry = load_registry(str(ROOT / "models" / "registry.yaml"))
    router = ModelRouter(registry)
    selected = router.select(EventType.PATIENT_VITAL)
    assert "anomaly_detector" in selected
    assert "risk_predictor" in selected


def test_bed_routes_to_capacity() -> None:
    registry = load_registry(str(ROOT / "models" / "registry.yaml"))
    router = ModelRouter(registry)
    selected = router.select(EventType.BED_STATUS)
    assert selected == ["capacity_forecaster", "data_quality_scorer"] or "capacity_forecaster" in selected


def test_appointment_routes_to_none() -> None:
    registry = load_registry(str(ROOT / "models" / "registry.yaml"))
    router = ModelRouter(registry)
    assert router.select(EventType.APPOINTMENT_EVENT) == []
