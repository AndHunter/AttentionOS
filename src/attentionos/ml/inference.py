"""Model metadata helpers.

The desktop UI uses this to show real model readiness. It does not fabricate
predictions when no trained model metadata exists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelMetadata:
    """Persisted model status."""

    is_trained: bool
    last_trained: str | None = None
    training_samples: int = 0
    validation_mae: float | None = None
    feature_count: int = 0
    model_version: str | None = None


def load_model_metadata(model_dir: Path) -> ModelMetadata:
    path = model_dir / "metadata.json"
    if not path.exists():
        return ModelMetadata(is_trained=False)
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return ModelMetadata(
            is_trained=bool(data.get("is_trained", False)),
            last_trained=data.get("last_trained"),
            training_samples=int(data.get("training_samples", 0)),
            validation_mae=data.get("validation_mae"),
            feature_count=int(data.get("feature_count", 0)),
            model_version=data.get("model_version"),
        )
    except Exception:
        return ModelMetadata(is_trained=False)
