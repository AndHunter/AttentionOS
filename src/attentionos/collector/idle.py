"""Idle tracker — detects user inactivity via WinAPI GetLastInputInfo."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# WinAPI structure for GetLastInputInfo
# ---------------------------------------------------------------------------


class LASTINPUTINFO(ctypes.Structure):
    """Win32 LASTINPUTINFO structure."""

    _fields_ = [
        ("cbSize", ctypes.wintypes.UINT),
        ("dwTime", ctypes.wintypes.DWORD),
    ]


def get_idle_duration_sec() -> float:
    """Return seconds since the last user input event (keyboard or mouse).

    Uses Win32 GetLastInputInfo + GetTickCount to compute elapsed idle time.
    Returns 0.0 if the API call fails.
    """
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)

    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):  # type: ignore[attr-defined]
        logger.warning("GetLastInputInfo failed.")
        return 0.0

    tick_count = ctypes.windll.kernel32.GetTickCount()  # type: ignore[attr-defined]

    # Handle tick count wraparound (every ~49.7 days)
    elapsed_ms = (tick_count - lii.dwTime) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


class IdleTracker:
    """Tracks idle state transitions based on a configurable threshold.

    Determines whether the user is currently idle and tracks
    idle burst count (transitions from active to idle).
    """

    def __init__(self, idle_threshold_sec: float = 120.0) -> None:
        self._threshold = idle_threshold_sec
        self._is_idle = False
        self._idle_burst_count = 0
        self._last_idle_start: float | None = None
        self._total_idle_time: float = 0.0

    @property
    def is_idle(self) -> bool:
        """Whether the user is currently considered idle."""
        return self._is_idle

    @property
    def idle_burst_count(self) -> int:
        """Number of idle→active transitions (idle bursts) since creation."""
        return self._idle_burst_count

    @property
    def total_idle_time(self) -> float:
        """Approximate total seconds the user has been idle since creation."""
        return self._total_idle_time

    def poll(self) -> tuple[float, bool, bool]:
        """Poll the current idle duration and update state.

        Returns:
            Tuple of:
                - idle_seconds: current idle duration
                - is_idle: whether user is considered idle right now
                - became_idle: whether this poll triggered a new idle period
        """
        idle_sec = get_idle_duration_sec()
        was_idle = self._is_idle
        self._is_idle = idle_sec >= self._threshold
        became_idle = False

        if self._is_idle and not was_idle:
            # Transition: active → idle
            became_idle = True
            self._idle_burst_count += 1
            self._last_idle_start = time.monotonic()
            logger.debug("User became idle (%.1fs)", idle_sec)

        elif not self._is_idle and was_idle:
            # Transition: idle → active
            if self._last_idle_start is not None:
                self._total_idle_time += time.monotonic() - self._last_idle_start
                self._last_idle_start = None
            logger.debug("User returned from idle.")

        return idle_sec, self._is_idle, became_idle

    def reset_burst_count(self) -> int:
        """Reset the idle burst counter and return the previous value."""
        count = self._idle_burst_count
        self._idle_burst_count = 0
        return count
