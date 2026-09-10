from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "gateway"))

from app.simulator import SCENARIOS, build_scenario_events  # noqa: E402


def test_deteriorating_patient_worsens() -> None:
    events = build_scenario_events("deteriorating_patient", count=10, patient_id="pat_10092")
    first = events[0]["payload"]["spo2"]
    last = events[-1]["payload"]["spo2"]
    assert last < first
    assert events[-1]["payload"]["heart_rate"] > events[0]["payload"]["heart_rate"]


def test_duplicate_storm_same_id() -> None:
    events = build_scenario_events("duplicate_storm", count=25, patient_id="pat_1")
    assert len({e["event_id"] for e in events}) == 1
    assert len(events) == 25


def test_all_scenarios_exist() -> None:
    for name in SCENARIOS:
        assert build_scenario_events(name, count=3, patient_id="pat_1")
