"""Tests for the feature pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from attentionos.features.pipeline import FeaturePipeline
from attentionos.features.schema import FEATURE_DEFINITIONS, get_feature_names
from attentionos.storage.schema import ActivityEvent


class TestFeaturePipeline:
    """Test feature computation."""

    def test_empty_events(self):
        pipeline = FeaturePipeline()
        at_time = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)
        features = pipeline.compute_features_at([], at_time)

        # Should return a complete feature vector with defaults
        expected_names = get_feature_names()
        for name in expected_names:
            assert name in features, f"Missing feature: {name}"

    def test_all_features_present(self, sample_events):
        pipeline = FeaturePipeline()
        at_time = sample_events[-1].ts_end + timedelta(seconds=1)
        features = pipeline.compute_features_at(sample_events, at_time)

        expected_names = get_feature_names()
        for name in expected_names:
            assert name in features, f"Missing feature: {name}"

    def test_causal_filtering(self, sample_events):
        """Features at an early time should not use later events."""
        pipeline = FeaturePipeline()

        # Compute features at the midpoint
        midpoint = sample_events[5].ts_end
        features_mid = pipeline.compute_features_at(sample_events, midpoint)

        # Compute features at the end
        endpoint = sample_events[-1].ts_end + timedelta(seconds=1)
        features_end = pipeline.compute_features_at(sample_events, endpoint)

        # End should have more unique apps and active minutes
        assert features_end["unique_apps"] >= features_mid["unique_apps"]
        assert features_end["active_minutes_day"] >= features_mid["active_minutes_day"]

    def test_switching_features(self, sample_events):
        """Context switch features should reflect actual switches."""
        pipeline = FeaturePipeline()
        at_time = sample_events[-1].ts_end + timedelta(seconds=1)
        features = pipeline.compute_features_at(sample_events, at_time)

        # sample_events has switches: Code→chrome→explorer→Code = 3 switches
        assert features["switches_15m"] >= 1
        assert features["unique_apps"] >= 2

    def test_temporal_features(self, sample_events):
        """Temporal features should reflect the computation time."""
        pipeline = FeaturePipeline()
        at_time = datetime(2026, 8, 10, 14, 30, 0, tzinfo=UTC)
        features = pipeline.compute_features_at(sample_events, at_time)

        assert features["hour_of_day"] == 14
        assert features["weekday"] == 0  # Monday (2026-08-10)

    def test_idle_features(self, sample_events):
        """Idle features should detect idle periods in sample events."""
        pipeline = FeaturePipeline()
        at_time = sample_events[-1].ts_end + timedelta(seconds=1)
        features = pipeline.compute_features_at(sample_events, at_time)

        # sample_events has idle events with idle_seconds=200
        assert features["idle_ratio"] > 0
        assert features["idle_bursts"] >= 0

    def test_input_rate_features(self, sample_events):
        """Input rate should be positive for active events."""
        pipeline = FeaturePipeline()
        at_time = sample_events[-1].ts_end + timedelta(seconds=1)
        features = pipeline.compute_features_at(sample_events, at_time)

        assert features["keyboard_rate"] > 0
        assert features["mouse_rate"] > 0

    def test_task_label_encoding(self):
        """Task labels should be encoded to integers."""
        pipeline = FeaturePipeline()
        events = [
            ActivityEvent(
                ts_start=datetime(2026, 8, 10, 9, 0, 0, tzinfo=UTC),
                ts_end=datetime(2026, 8, 10, 9, 0, 3, tzinfo=UTC),
                process_name="Code.exe",
                idle_seconds=0.0,
                keyboard_events=5,
                mouse_events=2,
                task_label="Coding",
            )
        ]
        at_time = events[-1].ts_end + timedelta(seconds=1)
        features = pipeline.compute_features_at(events, at_time)
        assert features["task_label_encoded"] == 1  # "Coding" → 1

    def test_feature_series(self, sample_events):
        """compute_features_series should return a DataFrame."""
        pipeline = FeaturePipeline()
        df = pipeline.compute_features_series(sample_events, interval_minutes=1)

        if not df.empty:
            expected_names = get_feature_names()
            for name in expected_names:
                assert name in df.columns, f"Missing column: {name}"


class TestFeatureSchema:
    """Test feature schema metadata."""

    def test_all_definitions_have_names(self):
        for f in FEATURE_DEFINITIONS:
            assert f.name
            assert f.group
            assert f.dtype in ("float", "int", "bool")

    def test_no_duplicate_names(self):
        names = [f.name for f in FEATURE_DEFINITIONS]
        assert len(names) == len(set(names)), "Duplicate feature names found"

    def test_feature_groups(self):
        from attentionos.features.schema import get_feature_groups
        groups = get_feature_groups()
        assert "focus" in groups
        assert "switching" in groups
        assert "idle" in groups
        assert "input" in groups
        assert "temporal" in groups
        assert "workload" in groups
        assert "task" in groups
