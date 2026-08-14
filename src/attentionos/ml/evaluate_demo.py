"""Evaluate saved demo model metadata and dataset distributions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("data/demo/synthetic_training_dataset.parquet"))
    parser.add_argument("--model-dir", type=Path, default=Path("models/demo"))
    args = parser.parse_args()
    metadata = json.loads((args.model_dir / "metadata.json").read_text(encoding="utf-8"))
    data = pd.read_parquet(args.dataset)
    report = {
        "metadata": metadata,
        "samples": int(len(data)),
        "target_distribution": data["current_effectiveness_target"].value_counts().sort_index().to_dict(),
        "decline_rate": float(data["decline_next_30m"].mean()),
        "break_benefit_mean": float(data["break_benefit_score"].mean()),
    }
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()

