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


class TaskAwareBaselineProfile:
    """Task/time aware baseline with global fallback.

    It is intentionally lightweight: this is infrastructure for future personal
    learning, not a claim that the personal model is already validated.
    """

    def __init__(self, window_size: int = 30, min_bucket_samples: int = 5) -> None:
        self.window_size = window_size
        self.min_bucket_samples = min_bucket_samples
        self.global_profile = PersonalBaselineProfile(window_size)
        self._task_profiles: dict[str, PersonalBaselineProfile] = {}
        self._hour_profiles: dict[int, PersonalBaselineProfile] = {}

    def update(
        self,
        features: dict[str, float | int],
        task_category: str | None = None,
        local_hour: int | None = None,
    ) -> None:
        self.global_profile.update(features)
        if task_category:
            profile = self._task_profiles.setdefault(
                task_category,
                PersonalBaselineProfile(self.window_size),
            )
            profile.update(features)
        if local_hour is not None:
            hour = int(local_hour) % 24
            profile = self._hour_profiles.setdefault(hour, PersonalBaselineProfile(self.window_size))
            profile.update(features)

    def relative_features(
        self,
        features: dict[str, float | int],
        task_category: str | None = None,
        local_hour: int | None = None,
    ) -> dict[str, float]:
        task_profile = self._usable_profile(self._task_profiles.get(task_category or ""))
        hour_profile = self._usable_profile(
            self._hour_profiles.get(int(local_hour) % 24) if local_hour is not None else None
        )
        global_relative = self.global_profile.relative_features(features)
        output = dict(global_relative)
        if task_profile is not None:
            output.update(
                {
                    f"task_{key}": value
                    for key, value in task_profile.relative_features(features).items()
                }
            )
        else:
            output.update({f"task_{key}": value for key, value in global_relative.items()})
        if hour_profile is not None:
            output.update(
                {
                    f"time_{key}": value
                    for key, value in hour_profile.relative_features(features).items()
                }
            )
        else:
            output.update({f"time_{key}": value for key, value in global_relative.items()})
        return output

    def stats(self, metric: str, task_category: str | None = None, local_hour: int | None = None) -> BaselineStats:
        task_profile = self._usable_profile(self._task_profiles.get(task_category or ""))
        if task_profile is not None:
            return task_profile.stats(metric)
        if local_hour is not None:
            hour_profile = self._usable_profile(self._hour_profiles.get(int(local_hour) % 24))
            if hour_profile is not None:
                return hour_profile.stats(metric)
        return self.global_profile.stats(metric)

    def _usable_profile(self, profile: PersonalBaselineProfile | None) -> PersonalBaselineProfile | None:
        if profile is None:
            return None
        counts = [profile.stats(metric).count for metric in PersonalBaselineProfile.METRICS]
        if max(counts, default=0) < self.min_bucket_samples:
            return None
        return profile


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
