from __future__ import annotations

from medflow_shared.features import extract_bed_features, extract_vital_features


def test_vital_features_mean_and_missing() -> None:
    current = {"heart_rate": 100, "spo2": 94, "respiratory_rate": 20}
    history = [
        {"heart_rate": 90, "spo2": 96, "respiratory_rate": 18},
        {"heart_rate": 100, "spo2": 94, "respiratory_rate": 20},
    ]
    feats = extract_vital_features(current, history)
    assert feats["heart_rate_mean_5m"] == 95
    assert feats["spo2_min_5m"] == 94
    assert feats["missing_ratio"] == 0


def test_vital_features_handles_gaps() -> None:
    current = {"heart_rate": 80, "spo2": None, "respiratory_rate": None}
    feats = extract_vital_features(current, [current])
    assert feats["missing_ratio"] > 0
    assert feats["spo2_mean_5m"] is None


def test_bed_occupancy() -> None:
    feats = extract_bed_features(
        {"occupancy_ratio": 0.92, "status": "occupied"},
        [{"occupancy_ratio": 0.8, "status": "occupied"}, {"occupancy_ratio": 0.92, "status": "occupied"}],
    )
    assert feats["occupancy_ratio"] == 0.92
    assert feats["occupied_count"] == 2
