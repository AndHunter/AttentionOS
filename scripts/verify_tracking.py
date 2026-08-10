"""Verify that Windows telemetry hooks can see foreground, idle, and input signals."""

from __future__ import annotations

import argparse
import ctypes
import time
from dataclasses import dataclass

from attentionos.collector.foreground import get_foreground_window
from attentionos.collector.idle import get_idle_duration_sec
from attentionos.collector.input_activity import InputCounter

KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_MOVE = 0x0001
VK_F24 = 0x87


@dataclass(frozen=True)
class VerificationResult:
    foreground_process: str
    foreground_hwnd: int
    idle_seconds: float
    keyboard_events: int
    mouse_events: int
    hooks_running: bool

    @property
    def ok(self) -> bool:
        return (
            bool(self.foreground_process)
            and self.foreground_hwnd > 0
            and self.idle_seconds >= 0
            and self.keyboard_events > 0
            and self.mouse_events > 0
            and self.hooks_running
        )


def _send_safe_input() -> None:
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    user32.keybd_event(VK_F24, 0, 0, 0)
    user32.keybd_event(VK_F24, 0, KEYEVENTF_KEYUP, 0)
    for delta in (1, -1, 1, -1):
        user32.mouse_event(MOUSEEVENTF_MOVE, delta, 0, 0, 0)


def verify_tracking(seconds: float = 2.0) -> VerificationResult:
    foreground = get_foreground_window(hash_title=True)
    idle_seconds = get_idle_duration_sec()
    counter = InputCounter()
    counter.start()
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            _send_safe_input()
            time.sleep(0.2)
        keyboard_events, mouse_events = counter.get_and_reset()
        return VerificationResult(
            foreground_process=foreground.process_name,
            foreground_hwnd=foreground.hwnd,
            idle_seconds=idle_seconds,
            keyboard_events=keyboard_events,
            mouse_events=mouse_events,
            hooks_running=counter.is_running,
        )
    finally:
        counter.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=2.0)
    args = parser.parse_args()

    result = verify_tracking(seconds=args.seconds)
    print("AttentionOS tracking verification")
    print(f"Foreground process: {result.foreground_process} (hwnd={result.foreground_hwnd})")
    print(f"Idle seconds: {result.idle_seconds:.2f}")
    print(f"Keyboard events counted: {result.keyboard_events}")
    print(f"Mouse events counted: {result.mouse_events}")
    print(f"Input hooks running: {result.hooks_running}")
    print(f"Result: {'PASS' if result.ok else 'FAIL'}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
