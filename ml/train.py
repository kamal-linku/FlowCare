import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

FEATURES = ["patients_ahead", "available_staff", "typical_service_minutes", "occupied_staff", "hour", "is_appointment"]
TARGET = "actual_wait_minutes"


def train(data_path: Path, artifact_path: Path) -> dict:
    frame = pd.read_csv(data_path, parse_dates=["arrival_at"]).sort_values("arrival_at")
    if len(frame) < 50:
        raise ValueError("At least 50 synthetic event rows are required for a chronological split.")
    split = int(len(frame) * 0.8)
    training, test = frame.iloc[:split], frame.iloc[split:]
    baseline = np.maximum(
        0,
        test["patients_ahead"].to_numpy() * test["typical_service_minutes"].to_numpy()
        / test["available_staff"].clip(lower=1).to_numpy()
        + test["occupied_staff"].to_numpy() * test["typical_service_minutes"].to_numpy()
        / test["available_staff"].clip(lower=1).to_numpy(),
    )
    model = RandomForestRegressor(n_estimators=120, min_samples_leaf=3, random_state=2025, n_jobs=-1)
    model.fit(training[FEATURES], training[TARGET])
    predictions = np.maximum(0, model.predict(test[FEATURES]))
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, artifact_path)
    metrics = {
        "data_type": "synthetic",
        "rows": int(len(frame)),
        "chronological_split": f"{split} train / {len(test)} test",
        "test_start": test["arrival_at"].min().isoformat(),
        "baseline_mae_minutes": round(mean_absolute_error(test[TARGET], baseline), 2),
        "random_forest_mae_minutes": round(mean_absolute_error(test[TARGET], predictions), 2),
        "baseline_rmse_minutes": round(float(np.sqrt(mean_squared_error(test[TARGET], baseline))), 2),
        "random_forest_rmse_minutes": round(float(np.sqrt(mean_squared_error(test[TARGET], predictions))), 2),
        "features": FEATURES,
        "warning": "Metrics are synthetic-only and do not establish hospital performance.",
    }
    metrics_path = artifact_path.with_name("evaluation.json")
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train and evaluate the FlowCare synthetic-data waiting model.")
    parser.add_argument("--data", type=Path, default=Path("ml/data/generated/synthetic_events.csv"))
    parser.add_argument("--artifact", type=Path, default=Path("ml/artifacts/wait_time_model.joblib"))
    arguments = parser.parse_args()
    train(arguments.data, arguments.artifact)
