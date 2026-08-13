# AttentionOS Tauri Shell

Modern React + Tauri desktop shell for AttentionOS.

This app is intentionally a presentation shell over the existing local-first
AttentionOS data. It reads `%LOCALAPPDATA%\AttentionOS\attentionos.db` directly
and does not replace or rewrite the Python telemetry collector yet.

## Commands

```powershell
npm install
npm run build
npm run lint
npm run tauri:dev
npm run tauri:build
```

## Native Build Prerequisites

- Rust / Cargo
- Visual Studio Build Tools with `Desktop development with C++`
- MSVC linker available as `link.exe`
- Windows SDK

If `cargo check` fails with `link.exe not found`, open Visual Studio Installer
and add the C++ desktop workload to the installed Build Tools instance.
