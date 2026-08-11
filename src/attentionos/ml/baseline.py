"""Robust personal baseline calculations."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class BaselineStats:
    """Robust statistics for one metric."""

    median: float
    iqr: float
    mad: float
    count: int


class PersonalBaselineProfile:
    """Rolling baseline using median, IQR, and MAD."""

    METRICS = [
        "context_switch_rate",
        "session_duration",
        "input_event_rate",
        "active_time",
        "focused_time_today",
    ]

    def __init__(self, window_size: int = 14) -> None:
        self.window_size = window_size
        self._values: dict[str, list[float]] = {metric: [] for metric in self.METRICS}

    def update(self, features: dict[str, float | int]) -> None:
        for metric in self.METRICS:
            if metric in features:
                values = self._values.setdefault(metric, [])
                values.append(float(features[metric]))
                self._values[metric] = values[-self.window_size :]

    def stats(self, metric: str) -> BaselineStats:
        values = self._values.get(metric, [])
        if not values:
            return BaselineStats(median=0.0, iqr=0.0, mad=0.0, count=0)
        med = float(median(values))
        sorted_values = sorted(values)
        q1 = _percentile(sorted_values, 25)
        q3 = _percentile(sorted_values, 75)
        deviations = [abs(value - med) for value in values]
        return BaselineStats(
            median=med,
            iqr=float(q3 - q1),
            mad=float(median(deviations)),
            count=len(values),
        )

    def relative_features(self, features: dict[str, float | int]) -> dict[str, float]:
        return {
            "switch_rate_vs_baseline": _ratio(
                float(features.get("context_switch_rate", 0.0)),
                self.stats("context_switch_rate").median,
            ),
            "session_length_vs_baseline": _ratio(
                float(features.get("session_duration", 0.0)),
                self.stats("session_duration").median,
            ),
            "input_rate_vs_baseline": _ratio(
                float(features.get("input_event_rate", 0.0)),
                self.stats("input_event_rate").median,
            ),
        }


def _ratio(value: float, baseline: float) -> float:
    if baseline <= 1e-9:
        return 0.0
    return value / baseline


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    position = (len(sorted_values) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction
