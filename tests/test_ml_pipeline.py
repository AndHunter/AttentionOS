from __future__ import annotations

from datetime import UTC, datetime, timedelta

from attentionos.ml.baseline import PersonalBaselineProfile, TaskAwareBaselineProfile
from attentionos.ml.dataset import build_effectiveness_dataset, chronological_split
from attentionos.ml.features import compute_feature_window
from attentionos.ml.train import train_effectiveness_baselines
from attentionos.storage.schema import ActivityEvent, SelfReport


def test_feature_window_generation(sample_events) -> None:
    start = sample_events[0].ts_start
    end = sample_events[-1].ts_end
    features = compute_feature_window(sample_events, start, end, sample_events)
    assert features["active_time"] > 0
    assert features["context_switch_count"] >= 1
    assert features["app_entropy"] >= 0


def test_personal_baseline_relative_features() -> None:
    baseline = PersonalBaselineProfile()
    baseline.update({"context_switch_rate": 2, "session_duration": 60, "input_event_rate": 10})
    relative = baseline.relative_features(
        {"context_switch_rate": 4, "session_duration": 120, "input_event_rate": 20}
    )
    assert relative["switch_rate_vs_baseline"] == 2
    assert relative["session_length_vs_baseline"] == 2


def test_task_aware_baseline_uses_task_and_time_buckets() -> None:
    baseline = TaskAwareBaselineProfile(min_bucket_samples=2)
    baseline.update({"context_switch_rate": 2, "session_duration": 60, "input_event_rate": 10}, "coding", 10)
    baseline.update({"context_switch_rate": 2, "session_duration": 60, "input_event_rate": 10}, "coding", 10)
    baseline.update({"context_switch_rate": 8, "session_duration": 20, "input_event_rate": 4}, "gaming", 23)
    relative = baseline.relative_features(
        {"context_switch_rate": 4, "session_duration": 120, "input_event_rate": 20},
        "coding",
        10,
    )
    assert relative["task_switch_rate_vs_baseline"] == 2
    assert relative["time_session_length_vs_baseline"] == 2


def test_task_aware_baseline_falls_back_to_global_when_bucket_is_small() -> None:
    baseline = TaskAwareBaselineProfile(min_bucket_samples=5)
    baseline.update({"context_switch_rate": 2, "session_duration": 60, "input_event_rate": 10}, "coding", 10)
    relative = baseline.relative_features(
        {"context_switch_rate": 4, "session_duration": 120, "input_event_rate": 20},
        "coding",
        10,
    )
    assert relative["task_switch_rate_vs_baseline"] == relative["switch_rate_vs_baseline"]


def test_dataset_ordering(sample_events) -> None:
    report_time = sample_events[-1].ts_end + timedelta(minutes=1)
    reports = [
        SelfReport(
            id=2,
            timestamp=report_time + timedelta(minutes=10),
            perceived_effectiveness=3,
            perceived_fatigue=2,
            task_difficulty=3,
        ),
        SelfReport(
            id=1,
            timestamp=report_time,
            perceived_effectiveness=4,
            perceived_fatigue=2,
            task_difficulty=3,
        ),
    ]
    dataset = build_effectiveness_dataset(sample_events, reports)
    assert list(dataset["report_id"]) == [1, 2]
    train, validation = chronological_split(dataset, validation_ratio=0.5)
    assert train["timestamp"].max() <= validation["timestamp"].min()


def test_ml_training_on_synthetic_dataset() -> None:
    base = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
    events = []
    reports = []
    for index in range(35):
        ts = base + timedelta(minutes=index * 35)
        for step in range(10):
            events.append(
                ActivityEvent(
                    ts_start=ts + timedelta(minutes=step),
                    ts_end=ts + timedelta(minutes=step + 1),
                    process_name="Code.exe" if index % 2 == 0 else "Chrome.exe",
                    idle_seconds=0,
                    keyboard_events=10 + index,
                    mouse_events=3,
                )
            )
        reports.append(
            SelfReport(
                timestamp=ts + timedelta(minutes=30),
                perceived_effectiveness=1 + (index % 5),
                perceived_fatigue=2,
                task_difficulty=3,
            )
        )
    dataset = build_effectiveness_dataset(events, reports)
    results = train_effectiveness_baselines(dataset)
    assert results
    assert results[0].mae >= 0
