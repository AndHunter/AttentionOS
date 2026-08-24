"""Generate synthetic demo data for AttentionOS.

Creates realistic work patterns with:
- Multiple applications with natural switching patterns
- Idle periods (breaks, lunch)
- Task labels and self-reports correlated with behavioral features
- Realistic time-of-day effects

Usage:
    python scripts/generate_demo_data.py [--days 5] [--output data/demo]
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from attentionos.storage.db import init_db, insert_events_batch, insert_self_report
from attentionos.storage.schema import ActivityEvent, SelfReport

# ---------------------------------------------------------------------------
# Simulation parameters
# ---------------------------------------------------------------------------

# Typical work apps and their weights (higher = more common)
APPS = [
    ("Code.exe", 0.30),
    ("python.exe", 0.15),
    ("chrome.exe", 0.20),
    ("explorer.exe", 0.05),
    ("Slack.exe", 0.08),
    ("Telegram.exe", 0.05),
    ("Notion.exe", 0.07),
    ("Spotify.exe", 0.03),
    ("WindowsTerminal.exe", 0.05),
    ("Obsidian.exe", 0.02),
]

TASK_LABELS = ["Coding", "ML", "Math", "English", "Rest", "Meeting", "Admin"]

# Time-of-day productivity profile (0-23h → productivity multiplier)
HOUR_PRODUCTIVITY = {
    8: 0.6, 9: 0.8, 10: 1.0, 11: 1.0, 12: 0.5,
    13: 0.4, 14: 0.7, 15: 0.9, 16: 1.0, 17: 0.8,
    18: 0.6, 19: 0.4, 20: 0.3,
}


def _weighted_choice(items: list[tuple[str, float]]) -> str:
    """Select a random item with given weights."""
    names, weights = zip(*items, strict=False)
    return random.choices(names, weights=weights, k=1)[0]


def _generate_day_events(
    day: date,
    polling_sec: float = 3.0,
    work_start_hour: int = 9,
    work_end_hour: int = 18,
) -> tuple[list[ActivityEvent], list[SelfReport]]:
    """Generate one day of synthetic activity events and self-reports."""

    events: list[ActivityEvent] = []
    reports: list[SelfReport] = []

    current_time = datetime.combine(
        day,
        datetime.min.time().replace(hour=work_start_hour),
        tzinfo=UTC,
    )
    end_time = datetime.combine(
        day,
        datetime.min.time().replace(hour=work_end_hour),
        tzinfo=UTC,
    )

    current_app = _weighted_choice(APPS)
    current_task = random.choice(TASK_LABELS[:4])  # Focus on productive tasks
    app_session_remaining = random.randint(20, 200)  # Events before switching
    is_on_break = False
    break_end_time = current_time
    last_report_time = current_time
    cumulative_fatigue = 0.0

    while current_time < end_time:
        hour = current_time.hour
        productivity = HOUR_PRODUCTIVITY.get(hour, 0.5)

        # --- Break / lunch logic ---
        if is_on_break:
            if current_time >= break_end_time:
                is_on_break = False
                cumulative_fatigue = max(0, cumulative_fatigue - 2.0)
            else:
                # Idle event during break
                events.append(
                    ActivityEvent(
                        ts_start=current_time,
                        ts_end=current_time + timedelta(seconds=polling_sec),
                        process_name="explorer.exe",
                        idle_seconds=300.0,
                        keyboard_events=0,
                        mouse_events=0,
                        task_label="Rest",
                        collector_version="0.5.0-demo",
                    )
                )
                current_time += timedelta(seconds=polling_sec)
                continue

        # --- Lunch break (12:00–13:00) ---
        if hour == 12 and not is_on_break and random.random() < 0.3:
            is_on_break = True
            break_end_time = current_time + timedelta(minutes=random.randint(30, 60))
            continue

        # --- Random short breaks ---
        if random.random() < 0.01 * (1 + cumulative_fatigue * 0.3):
            is_on_break = True
            break_end_time = current_time + timedelta(minutes=random.randint(3, 15))
            continue

        # --- App switching ---
        app_session_remaining -= 1
        if app_session_remaining <= 0:
            old_app = current_app
            current_app = _weighted_choice(APPS)
            # Avoid switching to same app
            while current_app == old_app and random.random() < 0.7:
                current_app = _weighted_choice(APPS)

            # Session length depends on productivity
            base_length = int(30 + productivity * 100)
            app_session_remaining = random.randint(
                max(5, base_length // 3), base_length
            )

            # Occasionally change task
            if random.random() < 0.2:
                current_task = random.choice(TASK_LABELS[:4])

        # --- Input activity ---
        # Higher productivity → more keyboard, fewer context switches
        base_kb = int(5 + productivity * 15 + random.gauss(0, 3))
        base_mouse = int(2 + 5 * (1 - productivity * 0.3) + random.gauss(0, 2))

        # Fatigue reduces input rate
        fatigue_factor = max(0.3, 1.0 - cumulative_fatigue * 0.1)
        kb_events = max(0, int(base_kb * fatigue_factor))
        mouse_events = max(0, int(base_mouse * fatigue_factor))

        # Idle seconds (brief micro-idles)
        idle_sec = 0.0
        if random.random() < 0.1 + cumulative_fatigue * 0.05:
            idle_sec = random.uniform(5, 60)

        events.append(
            ActivityEvent(
                ts_start=current_time,
                ts_end=current_time + timedelta(seconds=polling_sec),
                process_name=current_app,
                idle_seconds=idle_sec,
                keyboard_events=kb_events,
                mouse_events=mouse_events,
                task_label=current_task,
                collector_version="0.5.0-demo",
            )
        )

        # --- Fatigue accumulation ---
        cumulative_fatigue += 0.002  # Slow accumulation
        if hour >= 16:
            cumulative_fatigue += 0.003  # Faster in the afternoon

        # --- Self-reports every ~45 minutes ---
        if (current_time - last_report_time).total_seconds() >= 45 * 60:
            effectiveness = max(1, min(5, int(
                5 * productivity * fatigue_factor
                + random.gauss(0, 0.5)
            )))
            fatigue_score = max(1, min(5, int(
                1 + cumulative_fatigue * 1.5
                + random.gauss(0, 0.5)
            )))

            reports.append(
                SelfReport(
                    timestamp=current_time,
                    perceived_effectiveness=effectiveness,
                    perceived_fatigue=fatigue_score,
                    task_difficulty=random.randint(2, 4),
                )
            )
            last_report_time = current_time

        current_time += timedelta(seconds=polling_sec)

    return events, reports


def generate_demo_data(
    days: int = 5,
    db_path: Path | str | None = None,
    seed: int = 42,
) -> dict[str, int]:
    """Generate a full demo dataset.

    Args:
        days: Number of work days to generate.
        db_path: Path to SQLite database. If None, uses data/demo/demo.db.
        seed: Random seed for reproducibility.

    Returns:
        Dictionary with counts of generated events and reports.
    """
    random.seed(seed)

    if db_path is None:
        db_path = Path(__file__).resolve().parent.parent / "data" / "demo" / "demo.db"

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Clean start
    if db_path.exists():
        db_path.unlink()

    init_db(db_path)

    total_events = 0
    total_reports = 0
    start_date = date.today() - timedelta(days=days)

    for day_offset in range(days):
        current_day = start_date + timedelta(days=day_offset)

        # Skip weekends
        if current_day.weekday() >= 5:
            continue

        events, reports = _generate_day_events(current_day)
        count = insert_events_batch(events, db_path)
        total_events += count

        for report in reports:
            insert_self_report(report, db_path)
            total_reports += 1

        print(
            f"  Day {current_day}: {count} events, {len(reports)} self-reports"
        )

    stats = {
        "total_events": total_events,
        "total_reports": total_reports,
        "days": days,
        "db_path": str(db_path),
    }

    print(f"\n✅ Demo data generated: {total_events} events, {total_reports} reports")
    print(f"   Database: {db_path}")

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic demo data for AttentionOS")
    parser.add_argument("--days", type=int, default=5, help="Number of work days to generate")
    parser.add_argument("--output", type=str, default=None, help="Output database path")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    output = Path(args.output) if args.output else None
    generate_demo_data(days=args.days, db_path=output, seed=args.seed)


if __name__ == "__main__":
    main()
