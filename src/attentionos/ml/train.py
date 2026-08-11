"""Baseline supervised training for self-reported effectiveness."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error

from attentionos.ml.dataset import chronological_split

MIN_TRAINING_SAMPLES = 30
TARGET_COLUMN = "effectiveness"
NON_FEATURE_COLUMNS = {
    "report_id",
    "timestamp",
    "task_name",
    "window_start",
    "window_end",
    "effectiveness",
    "fatigue",
    "difficulty",
}


@dataclass(frozen=True)
class TrainingResult:
    """Training result metadata, safe to show only after training."""

    model_name: str
    train_size: int
    validation_size: int
    mae: float
    rmse: float
    spearman_corr: float | None
    feature_count: int


def train_effectiveness_baselines(dataset: pd.DataFrame) -> list[TrainingResult]:
    """Train simple baseline regressors using chronological validation."""
    if len(dataset) < MIN_TRAINING_SAMPLES:
        return []
    train_df, validation_df = chronological_split(dataset)
    feature_columns = [
        column
        for column in dataset.columns
        if column not in NON_FEATURE_COLUMNS and pd.api.types.is_numeric_dtype(dataset[column])
    ]
    x_train = train_df[feature_columns].fillna(0.0)
    y_train = train_df[TARGET_COLUMN].astype(float)
    x_val = validation_df[feature_columns].fillna(0.0)
    y_val = validation_df[TARGET_COLUMN].astype(float)
    models = [
        ("DummyRegressor", DummyRegressor(strategy="median")),
        ("Ridge", Ridge(alpha=1.0)),
        ("RandomForest", RandomForestRegressor(n_estimators=50, random_state=42)),
        ("HistGradientBoosting", HistGradientBoostingRegressor(random_state=42)),
    ]
    results: list[TrainingResult] = []
    for name, model in models:
        model.fit(x_train, y_train)
        prediction = np.clip(model.predict(x_val), 1, 5)
        results.append(
            TrainingResult(
                model_name=name,
                train_size=len(x_train),
                validation_size=len(x_val),
                mae=float(mean_absolute_error(y_val, prediction)),
                rmse=float(mean_squared_error(y_val, prediction) ** 0.5),
                spearman_corr=_spearman(y_val.to_numpy(), prediction),
                feature_count=len(feature_columns),
            )
        )
    return results


def _spearman(actual: np.ndarray, predicted: np.ndarray) -> float | None:
    if len(actual) < 2:
        return None
    actual_rank = pd.Series(actual).rank().to_numpy()
    predicted_rank = pd.Series(predicted).rank().to_numpy()
    corr = np.corrcoef(actual_rank, predicted_rank)[0, 1]
    if np.isnan(corr):
        return None
    return float(corr)
