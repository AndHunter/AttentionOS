# Verification Notes

Date: 2026-08-10
Platform: Windows 11, Python 3.13

## Commands

```powershell
python -m ruff check .
python -m pytest
python scripts\verify_tracking.py --seconds 2
powershell -ExecutionPolicy Bypass -File scripts\build_windows_exe.ps1 -Clean
```

## Results

- Ruff: passed.
- Pytest: 35 passed.
- Tracking diagnostic: passed.
- PyInstaller build: produced `dist\AttentionOS.exe`.
- EXE smoke test: process started and stayed alive for more than 6 seconds.

## Tracking Diagnostic Scope

The diagnostic validates:

- Foreground window process access through WinAPI.
- Idle time access through `GetLastInputInfo`.
- Keyboard event counting through low-level hooks.
- Mouse movement counting through low-level hooks.

The diagnostic sends safe synthetic `F24` key events and tiny relative mouse moves. It verifies counters, not typed content.
