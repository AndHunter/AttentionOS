# AttentionOS

Privacy-first personal performance intelligence for Windows.

AttentionOS is a local desktop application that observes behavioral work patterns,
collects self-reported effectiveness labels, and prepares a personal data pipeline
for future focus and performance modeling. It is not a Pomodoro timer, not a generic
time tracker, and not a productivity chatbot.

## Problem

People do not lose focus in the same way. AttentionOS is designed to learn from one
person's own work history instead of comparing them to a generic ideal worker.

The product loop is:

```text
Windows telemetry
        ↓
Local SQLite
        ↓
Feature engineering
        ↓
Personal baseline
        ↓
ML model
        ↓
Prediction
        ↓
Intervention
        ↓
Outcome feedback
```

## How It Works

AttentionOS observes foreground application changes, idle state, and aggregate
keyboard/mouse activity counts. The user can add quick self-reports for
effectiveness, fatigue, and task difficulty. Each self-report is linked to the
preceding telemetry window, making it usable later as supervised ML data.

## Architecture

```text
attentionos/
  collector/      Windows foreground, idle, and input counters
  desktop/        Tkinter desktop dashboard and settings UI
  storage/        SQLModel entities, SQLite access, migrations, export
  settings/       JSON-backed runtime preferences
  localization/   English/Russian translation resources
  sessions/       Derived activity sessions
  features/       Existing feature pipeline for rolling analytics
  ml/             Self-report dataset, feature windows, baseline, training infra
  interventions/  Future-ready heuristic/model intervention entities
```

## Current Features

- Native Windows desktop `.exe`.
- Calm data-first dashboard UI.
- Local SQLite telemetry persistence.
- Start/stop tracking from the desktop app.
- Task selection attached to telemetry events.
- Self-report check-ins using strict 1-5 scales.
- Settings page with language, tracking, privacy/data, notification, and model sections.
- English, Russian, and system-language fallback.
- Excluded applications that are ignored by telemetry.
- Structured JSON/CSV export for analysis and ML preparation.
- Safe SQLite migrations with schema versioning.

## Demo ML System

AttentionOS includes a synthetic-data demo model to demonstrate the intended
end-to-end personalization pipeline:

```text
Telemetry
        ↓
Rolling features
        ↓
Personal baseline
        ↓
CatBoost demo models
        ↓
Current effectiveness estimate
        ↓
Decline risk
        ↓
Break benefit / recommendation
        ↓
UI
```

**Demo model trained on synthetic data.**

**Демо-модель обучена на синтетических данных.**

Synthetic data is generated separately from the production SQLite database and is
stored under `data/demo/`:

```text
synthetic_telemetry.parquet
synthetic_reports.parquet
synthetic_interventions.parquet
synthetic_training_dataset.parquet
```

Synthetic metrics must not be interpreted as real-world validation. The demo
model does not diagnose fatigue, is not medically validated, and does not prove
quality on real users. It is a bootstrap experience for the future personal
model, which will require longitudinal real telemetry and enough self-reports.

CLI:

```powershell
python -m attentionos.ml.synthetic.generate --users 1000 --days 60 --seed 42
python -m attentionos.ml.train_demo
python -m attentionos.ml.evaluate_demo
python -m attentionos.ml.demo_sanity_check
python -m attentionos.ml.demo.inference
```

Models are saved under:

```text
models/demo/
  effectiveness.cbm
  decline.cbm
  break_benefit.cbm
  metadata.json
```

The Tauri dashboard displays demo predictions only with a visible `DEMO` badge
and the synthetic-data disclaimer.

## Personal ML Approach

The first real ML task is:

```text
Predict current self-reported effectiveness ∈ {1, 2, 3, 4, 5}
```

Self-reported effectiveness is used as the initial supervised learning target.
The initial model family is intentionally simple: dummy baseline, Ridge regression,
RandomForest, and HistGradientBoosting with chronological validation. No random
train/test split is used for time-dependent data.

Until enough real self-report samples exist, personal model status remains
`Collecting data`. Future versions can train a personal model from real
longitudinal data, separate from the synthetic demo model.

## Privacy

All telemetry is stored locally on this device.

AttentionOS never records:

- typed text;
- screenshots;
- clipboard content;
- microphone;
- camera.

Window titles are disabled by default in runtime settings. Keyboard and mouse
activity are stored only as aggregate counts.

AttentionOS does NOT diagnose fatigue or any medical/psychological condition.

## Screenshots

Dashboard screenshots are stored in:

- `docs/attentionos-redesign-dashboard.png`
- `docs/attentionos-redesign-dashboard-compact.png`

## Installation

```powershell
python -m pip install -e ".[dev,build,ml]"
attentionos
```

Build the desktop executable:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_exe.ps1 -Clean
```

The executable is created at:

```text
dist\AttentionOS.exe
```

## Tauri Desktop Shell

The modern React/Tauri shell lives in `attentionos-tauri/`. It reads the same
local SQLite database at `%LOCALAPPDATA%\AttentionOS\attentionos.db` and presents
the data-first dashboard, timeline, top apps, recent sessions, and notification
drawer without changing the existing Python telemetry collector.

```powershell
cd attentionos-tauri
npm install
npm run build
npm run tauri:dev
npm run tauri:build
```

Tauri native builds require Rust plus the Visual Studio C++ build tools workload
(`Desktop development with C++`, including MSVC `link.exe` and a Windows SDK).

## Verification

```powershell
python -m ruff check .
python -m pytest
python scripts/verify_tracking.py --seconds 2
```

## Roadmap

- Improve system tray/background behavior.
- Add persisted model metadata after first real training.
- Add controlled Train/Retrain flow once enough self-report data exists.
- Add intervention outcome tracking.
- Add dark mode after the theme system can support it cleanly.

## Project Status

Current phase: local-first desktop telemetry and personal ML data infrastructure.

The app collects real local telemetry and builds exportable supervised datasets,
but it does not claim to have a validated productivity model yet.

## License

MIT
