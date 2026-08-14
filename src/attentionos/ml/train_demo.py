"""Train CatBoost demo models on separated synthetic data."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    roc_auc_score,
)

from attentionos.ml.demo.features import CATEGORICAL_FEATURES, feature_schema


MODEL_VERSION = "demo-v1"


def train_demo(dataset_path: Path, model_dir: Path, seed: int = 42) -> dict[str, object]:
    from catboost import CatBoostClassifier, CatBoostRegressor, Pool

    data = pd.read_parquet(dataset_path).sort_values("timestamp").reset_index(drop=True)
    schema = feature_schema()
    features = schema.all
    cat_idx = [features.index(name) for name in CATEGORICAL_FEATURES]
    train, temporal, user_holdout = _splits(data)

    x_train = train[features]
    y_eff = train["current_effectiveness_target"].astype(float)
    y_decline = train["decline_next_30m"].astype(int)
    y_benefit = train["break_benefit_score"].astype(float)

    eff = CatBoostRegressor(iterations=220, depth=6, learning_rate=0.05, loss_function="MAE", random_seed=seed, verbose=0)
    decline = CatBoostClassifier(iterations=240, depth=6, learning_rate=0.045, loss_function="Logloss", random_seed=seed, verbose=0, auto_class_weights="Balanced")
    benefit = CatBoostRegressor(iterations=180, depth=5, learning_rate=0.055, loss_function="RMSE", random_seed=seed, verbose=0)
    pool = Pool(x_train, y_eff, cat_features=cat_idx)
    eff.fit(pool)
    decline.fit(Pool(x_train, y_decline, cat_features=cat_idx))
    benefit.fit(Pool(x_train, y_benefit, cat_features=cat_idx))

    model_dir.mkdir(parents=True, exist_ok=True)
    eff.save_model(model_dir / "effectiveness.cbm")
    decline.save_model(model_dir / "decline.cbm")
    benefit.save_model(model_dir / "break_benefit.cbm")

    metrics = {
        "temporal": _metrics(eff, decline, benefit, temporal, features, cat_idx),
        "user_holdout": _metrics(eff, decline, benefit, user_holdout, features, cat_idx),
        "baselines": _baseline_metrics(train, temporal, features),
    }
    importance = dict(
        sorted(
            zip(features, eff.get_feature_importance(Pool(x_train, cat_features=cat_idx)), strict=False),
            key=lambda item: abs(item[1]),
            reverse=True,
        )[:20]
    )
    metadata = {
        "model_version": MODEL_VERSION,
        "model_mode": "demo",
        "type": "Synthetic demo",
        "trained_at": datetime.now().isoformat(),
        "dataset_version": "synthetic-demo-v1",
        "samples": int(len(data)),
        "train_samples": int(len(train)),
        "temporal_samples": int(len(temporal)),
        "user_holdout_samples": int(len(user_holdout)),
        "features": features,
        "categorical_features": CATEGORICAL_FEATURES,
        "catboost_hyperparameters": {
            "effectiveness": {"iterations": 220, "depth": 6, "learning_rate": 0.05, "loss": "MAE"},
            "decline": {"iterations": 240, "depth": 6, "learning_rate": 0.045, "loss": "Logloss"},
            "break_benefit": {"iterations": 180, "depth": 5, "learning_rate": 0.055, "loss": "RMSE"},
        },
        "metrics": metrics,
        "feature_importance": importance,
        "disclaimer": "Demo model trained on synthetic data. Synthetic metrics are not real-world validation.",
        "disclaimer_ru": "Демо-модель обучена на синтетических данных.",
        "seed": seed,
    }
    (model_dir / "metadata.json").write_text(
        json.dumps(_json_safe(metadata), indent=2, allow_nan=False), encoding="utf-8"
    )
    return metadata


def _splits(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    users = sorted(data["user_id"].unique())
    holdout_users = set(users[max(int(len(users) * 0.85), 1) :])
    non_holdout = data[~data["user_id"].isin(holdout_users)]
    user_holdout = data[data["user_id"].isin(holdout_users)]
    cutoff = non_holdout["timestamp"].quantile(0.8)
    train = non_holdout[non_holdout["timestamp"] <= cutoff]
    temporal = non_holdout[non_holdout["timestamp"] > cutoff]
    return train, temporal, user_holdout


def _metrics(eff, decline, benefit, data: pd.DataFrame, features: list[str], cat_idx: list[int]) -> dict[str, float]:
    from catboost import Pool

    if data.empty:
        return {}
    pool = Pool(data[features], cat_features=cat_idx)
    eff_pred = np.clip(eff.predict(pool), 1, 5)
    decline_prob = decline.predict_proba(pool)[:, 1]
    benefit_pred = np.clip(benefit.predict(pool), 0, 1)
    y_decline = data["decline_next_30m"].astype(int)
    return {
        "effectiveness_mae": float(mean_absolute_error(data["current_effectiveness_target"], eff_pred)),
        "effectiveness_rmse": float(mean_squared_error(data["current_effectiveness_target"], eff_pred) ** 0.5),
        "effectiveness_spearman": float(pd.Series(eff_pred).corr(data["current_effectiveness_target"], method="spearman")),
        "decline_roc_auc": float(roc_auc_score(y_decline, decline_prob)) if y_decline.nunique() > 1 else 0.5,
        "decline_pr_auc": float(average_precision_score(y_decline, decline_prob)) if y_decline.nunique() > 1 else float(y_decline.mean()),
        "decline_logloss": float(log_loss(y_decline, decline_prob, labels=[0, 1])),
        "decline_brier": float(brier_score_loss(y_decline, decline_prob)),
        "break_benefit_mae": float(mean_absolute_error(data["break_benefit_score"], benefit_pred)),
    }


def _baseline_metrics(train: pd.DataFrame, valid: pd.DataFrame, features: list[str]) -> dict[str, float]:
    if valid.empty:
        return {}
    x_train = pd.get_dummies(train[features])
    x_valid = pd.get_dummies(valid[features]).reindex(columns=x_train.columns, fill_value=0)
    dummy = DummyRegressor(strategy="median").fit(x_train, train["current_effectiveness_target"])
    ridge = Ridge(alpha=1.0).fit(x_train, train["current_effectiveness_target"])
    return {
        "dummy_mae": float(mean_absolute_error(valid["current_effectiveness_target"], dummy.predict(x_valid))),
        "ridge_mae": float(mean_absolute_error(valid["current_effectiveness_target"], ridge.predict(x_valid))),
    }


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("data/demo/synthetic_training_dataset.parquet"))
    parser.add_argument("--model-dir", type=Path, default=Path("models/demo"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(train_demo(args.dataset, args.model_dir, args.seed), indent=2))


if __name__ == "__main__":
    main()
