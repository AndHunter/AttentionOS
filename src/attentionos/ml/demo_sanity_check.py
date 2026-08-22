"""Controlled sanity scenarios for demo recommendation behavior."""

from __future__ import annotations

import json

from attentionos.ml.demo.recommendation_engine import recommend_action


def run_scenarios() -> dict[str, object]:
    scenarios = {
        "A_stable_30m": recommend_action(4.0, 0.08, 0.12, 0.18, 0.12, 30, 30, 60).__dict__,
        "B_long_falling_input": recommend_action(2.2, 0.70, 0.78, 0.86, 0.72, 150, 150, 260).__dict__,
        "C_after_break": recommend_action(3.5, 0.12, 0.22, 0.28, 0.16, 18, 18, 120, break_count_today=1, last_break_duration=15).__dict__,
        "D_high_switch_tolerant": recommend_action(3.3, 0.25, 0.38, 0.46, 0.25, 55, 55, 150).__dict__,
    }
    expected = {
        "A_stable_30m": "low decline risk / continue",
        "B_long_falling_input": "higher risk / break likely",
        "C_after_break": "risk falls",
        "D_high_switch_tolerant": "smaller penalty when risk remains moderate",
    }
    return {"scenarios": scenarios, "expected": expected}


def main() -> None:
    print(json.dumps(run_scenarios(), indent=2))


if __name__ == "__main__":
    main()
