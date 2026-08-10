"""Foreground window tracker — detects active process via WinAPI."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import logging
from dataclasses import dataclass

import psutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# WinAPI bindings
# ---------------------------------------------------------------------------

user32 = ctypes.windll.user32  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]


def _get_foreground_hwnd() -> int:
    """Return the handle of the current foreground window."""
    return user32.GetForegroundWindow()


def _get_window_text(hwnd: int) -> str:
    """Return the title text of the given window handle."""
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_window_pid(hwnd: int) -> int:
    """Return the process ID that owns the given window."""
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _get_process_name(pid: int) -> str:
    """Return the executable name for a given PID, or 'Unknown' on failure."""
    try:
        proc = psutil.Process(pid)
        return proc.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return "Unknown"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ForegroundInfo:
    """Snapshot of the currently active foreground window."""

    process_name: str
    window_title: str
    window_title_hash: str
    pid: int
    hwnd: int


def get_foreground_window(hash_title: bool = True) -> ForegroundInfo:
    """Capture a snapshot of the current foreground window.

    Args:
        hash_title: If True, store SHA-256 of the title instead of raw text.

    Returns:
        ForegroundInfo with process name and optionally hashed title.
    """
    hwnd = _get_foreground_hwnd()
    title = _get_window_text(hwnd)
    pid = _get_window_pid(hwnd)
    process_name = _get_process_name(pid)

    title_hash = ""
    if hash_title and title:
        title_hash = hashlib.sha256(title.encode("utf-8", errors="replace")).hexdigest()[:16]

    return ForegroundInfo(
        process_name=process_name,
        window_title=title if not hash_title else "",
        window_title_hash=title_hash if hash_title else "",
        pid=pid,
        hwnd=hwnd,
    )


class ForegroundTracker:
    """Tracks foreground window changes between polling intervals.

    Detects context switches when the process_name changes.
    """

    def __init__(self, hash_titles: bool = True) -> None:
        self._hash_titles = hash_titles
        self._last_info: ForegroundInfo | None = None
        self._context_switch_count: int = 0

    @property
    def last_info(self) -> ForegroundInfo | None:
        """The most recent foreground window info."""
        return self._last_info

    @property
    def context_switch_count(self) -> int:
        """Total context switches detected since creation."""
        return self._context_switch_count

    def poll(self) -> tuple[ForegroundInfo, bool]:
        """Poll the current foreground window.

        Returns:
            Tuple of (current ForegroundInfo, whether a context switch occurred).
        """
        current = get_foreground_window(hash_title=self._hash_titles)
        is_switch = False

        if self._last_info is not None and current.process_name != self._last_info.process_name:
            is_switch = True
            self._context_switch_count += 1
            logger.debug(
                "Context switch: %s -> %s",
                self._last_info.process_name,
                current.process_name,
            )

        self._last_info = current
        return current, is_switch

    def reset_switch_count(self) -> int:
        """Reset the context switch counter and return the previous value."""
        count = self._context_switch_count
        self._context_switch_count = 0
        return count
