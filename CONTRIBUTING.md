# Contributing

AttentionOS is currently in data collection mode. Contributions should preserve reliability, privacy and reproducibility before adding new product surface.

## Before Opening a PR

```powershell
python -m pytest
cargo test --manifest-path .\attentionos-tauri\src-tauri\Cargo.toml
npm --prefix .\attentionos-tauri run build
```

Run `npm --prefix .\attentionos-tauri run tauri build` when touching the desktop shell, bundling or installer configuration.

## Privacy Rules

- Do not commit real SQLite databases, logs, exports, personal models or backups.
- Do not add telemetry that captures typed text, clipboard content, screenshots, microphone, camera or document contents.
- Keep synthetic/demo data clearly labeled as synthetic.
- Keep personal model logic in shadow mode unless a future activation decision is made explicitly.

## Code Style

Keep changes focused. Prefer existing modules and tests over broad rewrites. If a schema or feature meaning changes, bump the corresponding schema version.
