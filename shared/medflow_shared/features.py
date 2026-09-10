from __future__ import annotations

import statistics


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _var(values: list[float]) -> float | None:
    return statistics.pvariance(values) if len(values) > 1 else 0.0 if values else None


def _slope(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return (values[-1] - values[0]) / (len(values) - 1)


def extract_vital_features(current: dict, history: list[dict]) -> dict:
    hrs = [h["heart_rate"] for h in history if h.get("heart_rate") is not None]
    spo2s = [h["spo2"] for h in history if h.get("spo2") is not None]
    rrs = [h["respiratory_rate"] for h in history if h.get("respiratory_rate") is not None]
    features = {
        "heart_rate": current.get("heart_rate"),
        "spo2": current.get("spo2"),
        "respiratory_rate": current.get("respiratory_rate"),
        "temperature_c": current.get("temperature_c"),
        "systolic_bp": current.get("systolic_bp"),
        "diastolic_bp": current.get("diastolic_bp"),
        "heart_rate_mean_5m": _mean(hrs),
        "heart_rate_min_5m": min(hrs) if hrs else None,
        "heart_rate_max_5m": max(hrs) if hrs else None,
        "hr_variance_5m": _var(hrs),
        "hr_slope_5m": _slope(hrs),
        "spo2_mean_5m": _mean(spo2s),
        "spo2_min_5m": min(spo2s) if spo2s else None,
        "spo2_delta_5m": (current.get("spo2") - spo2s[0]) if current.get("spo2") is not None and spo2s else None,
        "rr_mean_5m": _mean(rrs),
        "observation_count": len(history),
    }
    missing = sum(1 for k in ("heart_rate", "spo2", "respiratory_rate") if current.get(k) is None)
    features["missing_ratio"] = missing / 3
    return features


def extract_bed_features(payload: dict, history: list[dict]) -> dict:
    ratios = [h.get("occupancy_ratio") for h in history if h.get("occupancy_ratio") is not None]
    occupied = sum(1 for h in history if h.get("status") == "occupied")
    available = sum(1 for h in history if h.get("status") == "available")
    return {
        "occupancy_ratio": payload.get("occupancy_ratio"),
        "occupied_count": occupied,
        "available_count": available,
        "occupancy_mean": _mean(ratios),
        "missing_ratio": 0.0 if payload.get("occupancy_ratio") is not None else 1.0,
    }


def extract_imaging_features(payload: dict) -> dict:
    acuity = {"low": 1, "medium": 2, "high": 3}.get(payload.get("acuity_hint") or "medium", 2)
    modality = {"XRAY": 1, "US": 2, "CT": 3, "MRI": 4, "PET": 5}.get(payload.get("modality"), 2)
    return {
        "waiting_minutes": payload.get("waiting_minutes", 0),
        "acuity_code": acuity,
        "modality_code": modality,
        "missing_ratio": 0.0,
    }
