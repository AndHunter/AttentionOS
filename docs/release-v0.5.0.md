# AttentionOS 0.5.0 Release Notes Draft

## Summary

AttentionOS 0.5.0 prepares the project for real-world data collection and public portfolio review.

## Highlights

- Tauri + React Windows desktop shell.
- Local SQLite telemetry storage.
- 24-hour timeline with app, task, idle and break segments.
- DEMO ML work/break recommendations trained on synthetic data.
- Recommendation accept/ignore feedback loop.
- Restart-safe break lifecycle and outcome capture.
- Data quality diagnostics and personal shadow-model diagnostics.
- Real-only ML dataset export with metadata.
- Structured runtime logging, backup rotation and daily health checks.

## Privacy

- Typed text is not recorded.
- Raw keystrokes are not recorded.
- Screenshots are not recorded.
- Clipboard, microphone, camera and document contents are not used.
- Real data stays local unless the user exports it.

## Artifacts To Attach

```text
AttentionOS_0.5.0_x64-setup.exe
AttentionOS_0.5.0_x64_en-US.msi
```

## Notes

The current user-facing model is a DEMO model trained on synthetic data. Real telemetry is used for outcome collection and future personalization, while the personal model remains in shadow mode.
