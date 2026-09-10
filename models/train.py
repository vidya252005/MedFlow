"""Train lightweight sklearn artifacts from synthetic 'normal' ward data."""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression


def main() -> None:
    rng = np.random.default_rng(42)
    n = 4000
    hr = rng.normal(78, 8, n).clip(50, 110)
    spo2 = rng.normal(98, 1.2, n).clip(94, 100)
    rr = rng.normal(16, 2, n).clip(10, 24)
    hr_mean = hr + rng.normal(0, 2, n)
    spo2_delta = rng.normal(0, 0.4, n)
    hr_var = rng.uniform(1, 12, n)
    x_anom = np.column_stack([hr, spo2, rr, hr_mean, spo2_delta, hr_var])

    iso = IsolationForest(n_estimators=80, contamination=0.03, random_state=42)
    iso.fit(x_anom)

    temp = rng.normal(36.8, 0.3, n)
    sbp = rng.normal(118, 10, n)
    y = ((hr > 110) | (spo2 < 93) | (rr > 26)).astype(int)
    # inject a few positives so the classifier is not degenerate
    y[:80] = 1
    x_risk = np.column_stack([hr, spo2, rr, temp, sbp, hr_mean])
    risk = LogisticRegression(max_iter=400)
    risk.fit(x_risk, y)

    out = Path(__file__).parent / "artifacts"
    out.mkdir(exist_ok=True)
    joblib.dump(iso, out / "anomaly_detector_v2.joblib")
    joblib.dump(risk, out / "risk_predictor_v1.joblib")
    print(f"wrote artifacts to {out}")


if __name__ == "__main__":
    main()
