"""Personal state model — supervised ML for predicting perceived effectiveness.

Supports:
- LogisticRegression (fast, interpretable baseline)
- CatBoost (strong gradient boosting for tabular data)

All training uses strict temporal split to prevent data leakage.
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


@dataclass
class ModelMetrics:
    """Evaluation metrics for a trained model."""

    model_name: str
    task: Literal["classification", "regression"]
    train_size: int
    test_size: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Classification
    roc_auc: float | None = None
    pr_auc: float | None = None
    f1: float | None = None
    accuracy: float | None = None

    # Regression
    mae: float | None = None
    spearman_corr: float | None = None

    # Baseline comparison
    naive_baseline_metric: float | None = None
    improvement_over_baseline: float | None = None

    feature_importances: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class ModelCard:
    """Documentation for a trained model."""

    name: str
    version: str
    target: str
    task: str
    features_used: list[str]
    training_period: str
    metrics: ModelMetrics
    limitations: list[str]
    leakage_risks: list[str]

    def to_markdown(self) -> str:
        md = f"# Model Card: {self.name}\n\n"
        md += f"**Version**: {self.version}\n"
        md += f"**Target**: {self.target}\n"
        md += f"**Task**: {self.task}\n"
        md += f"**Training period**: {self.training_period}\n\n"

        md += "## Metrics\n\n"
        for k, v in self.metrics.to_dict().items():
            if k not in ("model_name", "task", "timestamp", "feature_importances"):
                md += f"- **{k}**: {v}\n"

        md += "\n## Top Features\n\n"
        sorted_fi = sorted(
            self.metrics.feature_importances.items(), key=lambda x: abs(x[1]), reverse=True
        )
        for name, imp in sorted_fi[:10]:
            md += f"- {name}: {imp:.4f}\n"

        md += "\n## Limitations\n\n"
        for lim in self.limitations:
            md += f"- {lim}\n"

        md += "\n## Leakage Risks\n\n"
        for risk in self.leakage_risks:
            md += f"- {risk}\n"

        return md


class PersonalStateModel:
    """Supervised model for predicting perceived effectiveness.

    Supports two backends:
    - 'logreg': LogisticRegression (L2, calibrated)
    - 'catboost': CatBoostClassifier (gradient boosting)

    Classification target: low_performance = effectiveness <= 2
    """

    FEATURE_COLUMNS: list[str] = [
        "mean_focus_block_sec",
        "max_focus_block_sec",
        "uninterrupted_ratio",
        "switches_15m",
        "switches_30m",
        "switches_60m",
        "unique_apps",
        "switch_entropy",
        "idle_ratio",
        "idle_bursts",
        "time_since_last_break_min",
        "keyboard_rate",
        "mouse_rate",
        "kb_rate_change_pct",
        "mouse_rate_change_pct",
        "hour_of_day",
        "hour_sin",
        "hour_cos",
        "weekday",
        "session_age_min",
        "work_since_day_start_min",
        "active_minutes_2h",
        "active_minutes_day",
        "previous_session_length_min",
        "task_label_encoded",
    ]

    def __init__(
        self,
        model_type: Literal["logreg", "catboost"] = "logreg",
        low_perf_threshold: int = 2,
    ) -> None:
        self.model_type = model_type
        self.low_perf_threshold = low_perf_threshold
        self.model: Any = None
        self.scaler: StandardScaler | None = None
        self.is_trained = False
        self.metrics: ModelMetrics | None = None
        self.model_card: ModelCard | None = None

    def _create_model(self) -> Any:
        """Create the underlying ML model."""
        if self.model_type == "logreg":
            return LogisticRegression(
                C=1.0,
                max_iter=1000,
                class_weight="balanced",
                solver="lbfgs",
                random_state=42,
            )
        elif self.model_type == "catboost":
            try:
                from catboost import CatBoostClassifier

                return CatBoostClassifier(
                    iterations=300,
                    depth=6,
                    learning_rate=0.05,
                    loss_function="Logloss",
                    auto_class_weights="Balanced",
                    random_seed=42,
                    verbose=0,
                )
            except ImportError:
                logger.warning("CatBoost not installed, falling back to LogisticRegression.")
                self.model_type = "logreg"
                return self._create_model()
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")

    def prepare_dataset(
        self, features_df: pd.DataFrame, reports_df: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Align features with self-report labels.

        For each self-report, find the closest feature vector computed
        BEFORE the report timestamp.

        Args:
            features_df: DataFrame with timestamp index and feature columns.
            reports_df: DataFrame with timestamp, perceived_effectiveness columns.

        Returns:
            (X, y) where y is binary: 1 = low performance, 0 = normal.
        """
        if features_df.empty or reports_df.empty:
            return pd.DataFrame(), pd.Series(dtype=float)

        # Ensure datetime index
        if not isinstance(features_df.index, pd.DatetimeIndex):
            features_df = features_df.set_index("timestamp")

        rows: list[dict] = []
        for _, report in reports_df.iterrows():
            report_time = pd.Timestamp(report["timestamp"])
            # Find closest feature vector BEFORE report time
            valid = features_df[features_df.index <= report_time]
            if valid.empty:
                continue
            closest_idx = valid.index[-1]
            feature_row = valid.loc[closest_idx].to_dict()
            feature_row["effectiveness"] = report["perceived_effectiveness"]
            rows.append(feature_row)

        if not rows:
            return pd.DataFrame(), pd.Series(dtype=float)

        dataset = pd.DataFrame(rows)

        # Select only model features
        available_cols = [c for c in self.FEATURE_COLUMNS if c in dataset.columns]
        X = dataset[available_cols].fillna(0).astype(float)
        y = (dataset["effectiveness"] <= self.low_perf_threshold).astype(int)

        return X, y

    def temporal_split(
        self, X: pd.DataFrame, y: pd.Series, test_ratio: float = 0.25
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        """Split data chronologically (no shuffling — prevents leakage).

        Args:
            X: Feature matrix.
            y: Labels.
            test_ratio: Fraction for test set (taken from the end).

        Returns:
            (X_train, X_test, y_train, y_test)
        """
        split_idx = int(len(X) * (1 - test_ratio))
        return (
            X.iloc[:split_idx],
            X.iloc[split_idx:],
            y.iloc[:split_idx],
            y.iloc[split_idx:],
        )

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_test: pd.DataFrame,
        y_test: pd.Series,
    ) -> ModelMetrics:
        """Train the model and evaluate on test set.

        Args:
            X_train, y_train: Training data.
            X_test, y_test: Test data (temporal holdout).

        Returns:
            ModelMetrics with all evaluation results.
        """
        logger.info(
            "Training %s model: %d train, %d test samples",
            self.model_type,
            len(X_train),
            len(X_test),
        )

        # Scale features for LogReg
        self.scaler = StandardScaler()
        X_train_scaled = pd.DataFrame(
            self.scaler.fit_transform(X_train),
            columns=X_train.columns,
            index=X_train.index,
        )
        X_test_scaled = pd.DataFrame(
            self.scaler.transform(X_test),
            columns=X_test.columns,
            index=X_test.index,
        )

        # Create and train model
        self.model = self._create_model()

        if self.model_type == "logreg":
            self.model.fit(X_train_scaled, y_train)
            y_pred = self.model.predict(X_test_scaled)
            y_prob = self.model.predict_proba(X_test_scaled)[:, 1]
        else:
            # CatBoost doesn't need scaling
            self.model.fit(X_train, y_train)
            y_pred = self.model.predict(X_test)
            y_prob = self.model.predict_proba(X_test)[:, 1]

        self.is_trained = True

        # Compute metrics
        metrics = ModelMetrics(
            model_name=self.model_type,
            task="classification",
            train_size=len(X_train),
            test_size=len(X_test),
        )

        metrics.accuracy = float(accuracy_score(y_test, y_pred))
        metrics.f1 = float(f1_score(y_test, y_pred, zero_division=0))

        try:
            metrics.roc_auc = float(roc_auc_score(y_test, y_prob))
        except ValueError:
            metrics.roc_auc = None

        # PR-AUC
        try:
            precision, recall, _ = precision_recall_curve(y_test, y_prob)
            metrics.pr_auc = float(np.trapz(precision, recall))
        except ValueError:
            metrics.pr_auc = None

        # Naive baseline: always predict majority class
        majority_class = int(y_train.mode().iloc[0])
        naive_acc = float(accuracy_score(y_test, [majority_class] * len(y_test)))
        metrics.naive_baseline_metric = naive_acc
        metrics.improvement_over_baseline = (
            (metrics.accuracy - naive_acc) / max(naive_acc, 0.01) * 100
        )

        # Feature importances
        if self.model_type == "logreg":
            importances = dict(
                zip(X_train.columns, self.model.coef_[0].tolist(), strict=False)
            )
        elif self.model_type == "catboost":
            importances = dict(
                zip(
                    X_train.columns,
                    self.model.get_feature_importance().tolist(),
                    strict=False,
                )
            )
        else:
            importances = {}

        metrics.feature_importances = importances
        self.metrics = metrics

        # Build model card
        self.model_card = ModelCard(
            name=f"AttentionOS-{self.model_type}",
            version="0.5.0",
            target=f"low_performance (effectiveness <= {self.low_perf_threshold})",
            task="Binary classification",
            features_used=list(X_train.columns),
            training_period=f"{len(X_train)} samples (temporal split)",
            metrics=metrics,
            limitations=[
                "Single-user model — may not generalize to other people.",
                "Self-report labels are subjective and potentially noisy.",
                "Small dataset — results may not be stable.",
                "No medical claims — patterns only, not diagnoses.",
            ],
            leakage_risks=[
                "Features computed with rolling windows must be strictly causal.",
                "Temporal split used (no random shuffle) to prevent future leakage.",
                "Self-report timing relative to feature window must be checked.",
            ],
        )

        logger.info(
            "Model trained: accuracy=%.3f, F1=%.3f, ROC-AUC=%s",
            metrics.accuracy,
            metrics.f1,
            metrics.roc_auc,
        )

        return metrics

    def predict(self, features: dict[str, float | int]) -> tuple[float, float]:
        """Predict low-performance probability for a single feature vector.

        Args:
            features: Feature dict from FeaturePipeline.

        Returns:
            (probability_low_performance, confidence)
            where confidence = abs(probability - 0.5) * 2
        """
        if not self.is_trained or self.model is None:
            return 0.0, 0.0

        X = pd.DataFrame([{c: features.get(c, 0) for c in self.FEATURE_COLUMNS}])
        X = X.fillna(0).astype(float)

        if self.model_type == "logreg" and self.scaler is not None:
            X_scaled = pd.DataFrame(
                self.scaler.transform(X), columns=X.columns
            )
            prob = float(self.model.predict_proba(X_scaled)[0, 1])
        else:
            prob = float(self.model.predict_proba(X)[0, 1])

        confidence = abs(prob - 0.5) * 2  # 0.0 at 50%, 1.0 at 0% or 100%
        return prob, confidence

    def save(self, path: Path | str) -> None:
        """Save model, scaler, and metrics to disk."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        with open(path / "model.pkl", "wb") as f:
            pickle.dump(self.model, f)

        if self.scaler is not None:
            with open(path / "scaler.pkl", "wb") as f:
                pickle.dump(self.scaler, f)

        if self.metrics is not None:
            with open(path / "metrics.json", "w") as f:
                json.dump(self.metrics.to_dict(), f, indent=2, default=str)

        if self.model_card is not None:
            with open(path / "model_card.md", "w") as f:
                f.write(self.model_card.to_markdown())

        # Save metadata
        meta = {
            "model_type": self.model_type,
            "low_perf_threshold": self.low_perf_threshold,
            "feature_columns": self.FEATURE_COLUMNS,
            "is_trained": self.is_trained,
        }
        with open(path / "metadata.json", "w") as f:
            json.dump(meta, f, indent=2)

        logger.info("Model saved to %s", path)

    @classmethod
    def load(cls, path: Path | str) -> PersonalStateModel:
        """Load a saved model from disk."""
        path = Path(path)

        with open(path / "metadata.json") as f:
            meta = json.load(f)

        instance = cls(
            model_type=meta["model_type"],
            low_perf_threshold=meta["low_perf_threshold"],
        )

        with open(path / "model.pkl", "rb") as f:
            instance.model = pickle.load(f)

        scaler_path = path / "scaler.pkl"
        if scaler_path.exists():
            with open(scaler_path, "rb") as f:
                instance.scaler = pickle.load(f)

        metrics_path = path / "metrics.json"
        if metrics_path.exists():
            with open(metrics_path) as f:
                data = json.load(f)
                instance.metrics = ModelMetrics(**data)

        instance.is_trained = meta.get("is_trained", True)
        logger.info("Model loaded from %s", path)
        return instance
