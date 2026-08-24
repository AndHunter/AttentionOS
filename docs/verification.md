# Verification Notes

Date: 2026-08-24
Platform: Windows 11, Python 3.13, Node 24, Rust 1.97

## Commands

```powershell
python -m pytest
cargo test --manifest-path .\attentionos-tauri\src-tauri\Cargo.toml
npm --prefix .\attentionos-tauri run build
npm --prefix .\attentionos-tauri run tauri build
```

## Results

- Pytest: 76 passed.
- Cargo tests: 9 passed.
- React/Vite build: passed.
- Tauri build: produced Windows EXE, NSIS setup and MSI artifacts.
- Smoke launch: `app.exe` started and stayed alive for more than 5 seconds.

## Tracking Diagnostic Scope

The diagnostic validates:

- Foreground window process access through WinAPI.
- Idle time access through `GetLastInputInfo`.
- Keyboard event counting through low-level hooks.
- Mouse movement counting through low-level hooks.

The diagnostic sends safe synthetic `F24` key events and tiny relative mouse moves. It verifies counters, not typed content.
