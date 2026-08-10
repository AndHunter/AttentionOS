# AttentionOS

Native Windows desktop tracker for local-first personal focus analytics.

AttentionOS watches the active foreground application, idle time, and aggregate keyboard/mouse activity counters. It turns those local signals into daily sessions, focus blocks, switching metrics, and self-reports without storing keystroke content or uploading personal telemetry.

## Highlights

- Native desktop app with a calm, high-contrast dashboard.
- One-click tracking from the desktop UI.
- Local SQLite storage under `%LOCALAPPDATA%\AttentionOS`.
- Privacy-first telemetry: process names, hashed window titles, idle seconds, and input counts only.
- Session analytics for active time, focus blocks, app distribution, context switches, and input volume.
- PyInstaller build pipeline for a real Windows `.exe`.
- Windows CI that runs tests and builds the executable artifact.

## Quick Start

```powershell
python -m pip install -e ".[dev,build]"
attentionos
```

To build the desktop executable:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_exe.ps1 -Clean
```

The executable is created at:

```text
dist\AttentionOS.exe
```

## Verify Tracking

Run the diagnostic from Windows:

```powershell
python scripts/verify_tracking.py --seconds 2
```

The diagnostic checks foreground-window access, idle-time access, keyboard hook counting, and mouse movement counting. It sends safe synthetic `F24` key events and tiny relative mouse movements so no typed text is produced.

Expected result:

```text
Result: PASS
```

## Architecture

```text
Windows foreground window, idle state, and input hooks
        |
        v
Telemetry collector
        |
        v
Local SQLite event store
        |
        v
Session builder and feature pipeline
        |
        v
Native desktop dashboard and optional ML model
```

## Privacy Model

AttentionOS is built for personal use on your own computer.

- It is not a keylogger. It stores counts, never typed content.
- Window titles are hashed by default.
- Telemetry remains local in SQLite.
- Databases, logs, generated models, and build output are ignored by git.
- The app is not a medical product and does not diagnose attention, ADHD, burnout, or depression.

## Development

```powershell
python -m pip install -e ".[dev,build,ml]"
python -m pytest
python -m ruff check .
```

Legacy Streamlit dashboard:

```powershell
attentionos-ui
```

## Repository Status

Current phase: native desktop telemetry MVP.

Primary validation:

- Unit tests for storage, sessions, features, and desktop presentation helpers.
- Windows tracking diagnostic via `scripts/verify_tracking.py`.
- PyInstaller executable build via `scripts/build_windows_exe.ps1`.

See `docs/verification.md` for the latest local validation record.

## License

MIT
