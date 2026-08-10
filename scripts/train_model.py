"""Train the PersonalStateModel on historical data."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlmodel import select

from attentionos.features.pipeline import FeaturePipeline
from attentionos.models.trainer import PersonalStateModel
from attentionos.storage.db import get_session
from attentionos.storage.schema import ActivityEvent, SelfReport

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train PersonalStateModel")
    parser.add_argument(
        "--db-path",
        type=str,
        default="data/demo/demo.db",
        help="Path to database",
    )
    parser.add_argument(
        "--model-dir",
        type=str,
        default="data/models/latest",
        help="Output directory",
    )
    parser.add_argument(
        "--model-type",
        type=str,
        choices=["logreg", "catboost"],
        default="catboost",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    model_dir = Path(args.model_dir)

    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        return

    logger.info("Loading data from %s...", db_path)
    with get_session(db_path) as session:
        # Load all events
        events = session.exec(select(ActivityEvent).order_by(ActivityEvent.ts_start)).all()
        # Load all self-reports
        reports = session.exec(select(SelfReport).order_by(SelfReport.timestamp)).all()

    if not events:
        logger.error("No activity events found in database.")
        return
    if not reports:
        logger.error("No self-reports found in database. Cannot train model.")
        return

    logger.info("Loaded %d events and %d self-reports.", len(events), len(reports))

    # Compute features ONLY at the timestamps of the self-reports
    logger.info("Computing causal features for each self-report...")
    pipeline = FeaturePipeline()

    rows = []
    for r in reports:
        # compute_features_at will automatically filter events causally
        feat = pipeline.compute_features_at(events, r.timestamp)
        feat["effectiveness"] = r.perceived_effectiveness
        feat["timestamp"] = r.timestamp
        rows.append(feat)

    if not rows:
        logger.error("Failed to compute features.")
        return

    dataset = pd.DataFrame(rows)

    logger.info("Initializing %s model...", args.model_type)
    model = PersonalStateModel(model_type=args.model_type, low_perf_threshold=2)

    # We manually align features and labels here since we bypassed prepare_dataset.
    available_cols = [c for c in model.FEATURE_COLUMNS if c in dataset.columns]
    x = dataset[available_cols].fillna(0).astype(float)
    y = (dataset["effectiveness"] <= model.low_perf_threshold).astype(int)

    if len(x) < 10:
        logger.error("Not enough aligned data points for training (found %d, need >= 10).", len(x))
        return

    # Temporal split: last 20% is test
    logger.info("Splitting dataset temporally (80/20)...")
    x_train, x_test, y_train, y_test = model.temporal_split(x, y, test_ratio=0.2)

    # Check if we have both classes in train set
    if len(y_train.unique()) < 2:
        logger.warning("Train set contains only one class! Model will be trivial.")

    logger.info("Training...")
    metrics = model.train(x_train, y_train, x_test, y_test)

    # Save model
    model.save(model_dir)

    print("\n" + "="*50)
    print(" TRAINING COMPLETE ")
    print("="*50)
    print(f"Model saved to: {model_dir}")
    print(f"Accuracy: {metrics.accuracy:.2f}")
    if metrics.roc_auc is not None:
        print(f"ROC-AUC:  {metrics.roc_auc:.2f}")
    print(f"F1 Score: {metrics.f1:.2f}")
    if metrics.improvement_over_baseline is not None:
        print(f"Improvement over baseline: {metrics.improvement_over_baseline:+.1f}%")
    print("="*50)
    print("Top 3 features driving predictions:")
    sorted_fi = sorted(metrics.feature_importances.items(), key=lambda x: abs(x[1]), reverse=True)
    for name, imp in sorted_fi[:3]:
        print(f" - {name}: {imp:.4f}")
    print("="*50)


if __name__ == "__main__":
    main()
