"""Input activity counter — keyboard and mouse event counting via WinAPI.

Privacy note: this module counts events only. No keystroke content,
key identifiers, or mouse coordinates are ever stored.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import threading
import time

logger = logging.getLogger(__name__)
user32 = ctypes.windll.user32  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# WinAPI constants for low-level hooks
# ---------------------------------------------------------------------------

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_MOUSEMOVE = 0x0200

# Callback type for SetWindowsHookEx
HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.LPARAM,  # return
    ctypes.c_int,  # nCode
    ctypes.wintypes.WPARAM,  # wParam
    ctypes.wintypes.LPARAM,  # lParam
)

HHOOK = ctypes.wintypes.HANDLE
user32.CallNextHookEx.argtypes = [
    HHOOK,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
user32.CallNextHookEx.restype = ctypes.wintypes.LPARAM
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    HOOKPROC,
    ctypes.wintypes.HINSTANCE,
    ctypes.wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = HHOOK
user32.UnhookWindowsHookEx.argtypes = [HHOOK]
user32.UnhookWindowsHookEx.restype = ctypes.wintypes.BOOL


class InputCounter:
    """Counts keyboard and mouse events using low-level Windows hooks.

    Only aggregate counts are tracked — no content, key codes, or coordinates.
    The hooks run in a dedicated thread with their own message loop.
    """

    def __init__(self) -> None:
        self._keyboard_count: int = 0
        self._mouse_click_count: int = 0
        self._mouse_move_count: int = 0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._hooks_installed = False

        # Store references to prevent garbage collection
        self._kb_hook_proc: HOOKPROC | None = None
        self._mouse_hook_proc: HOOKPROC | None = None
        self._kb_hook_id: int = 0
        self._mouse_hook_id: int = 0

    # -----------------------------------------------------------------------
    # Hook callbacks
    # -----------------------------------------------------------------------

    def _keyboard_callback(
        self, nCode: int, wParam: int, lParam: int  # noqa: N803
    ) -> int:
        """Low-level keyboard hook — only increments counter."""
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            with self._lock:
                self._keyboard_count += 1
        return user32.CallNextHookEx(self._kb_hook_id, nCode, wParam, lParam)

    def _mouse_callback(
        self, nCode: int, wParam: int, lParam: int  # noqa: N803
    ) -> int:
        """Low-level mouse hook — counts clicks and movement."""
        if nCode >= 0:
            if wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
                with self._lock:
                    self._mouse_click_count += 1
            elif wParam == WM_MOUSEMOVE:
                # Count movement in reduced resolution (every Nth move)
                with self._lock:
                    self._mouse_move_count += 1
        return user32.CallNextHookEx(self._mouse_hook_id, nCode, wParam, lParam)

    # -----------------------------------------------------------------------
    # Thread management
    # -----------------------------------------------------------------------

    def _hook_thread(self) -> None:
        """Install hooks and run a Win32 message loop."""
        try:
            self._kb_hook_proc = HOOKPROC(self._keyboard_callback)
            self._mouse_hook_proc = HOOKPROC(self._mouse_callback)

            self._kb_hook_id = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, self._kb_hook_proc, None, 0
            )
            self._mouse_hook_id = user32.SetWindowsHookExW(
                WH_MOUSE_LL, self._mouse_hook_proc, None, 0
            )

            if not self._kb_hook_id or not self._mouse_hook_id:
                logger.error(
                    "Failed to install input hooks (kb=%s, mouse=%s)",
                    self._kb_hook_id,
                    self._mouse_hook_id,
                )
                return

            self._hooks_installed = True
            logger.info("Input activity hooks installed.")

            # Win32 message loop — required for hooks to work
            msg = ctypes.wintypes.MSG()
            while self._running:
                result = user32.PeekMessageW(
                    ctypes.byref(msg), None, 0, 0, 1  # PM_REMOVE
                )
                if result:
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.01)  # Prevent busy-wait

        except Exception:
            logger.exception("Error in input hook thread.")
        finally:
            self._unhook()

    def _unhook(self) -> None:
        """Remove installed hooks."""
        if self._kb_hook_id:
            user32.UnhookWindowsHookEx(self._kb_hook_id)
            self._kb_hook_id = 0
        if self._mouse_hook_id:
            user32.UnhookWindowsHookEx(self._mouse_hook_id)
            self._mouse_hook_id = 0
        self._hooks_installed = False
        logger.info("Input hooks removed.")

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """Start the input counting thread with hooks."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._hook_thread, daemon=True, name="input-hooks")
        self._thread.start()
        # Wait briefly for hooks to install
        for _ in range(50):
            if self._hooks_installed:
                break
            time.sleep(0.02)

    def stop(self) -> None:
        """Stop the input counting thread and remove hooks."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Input counter stopped.")

    def get_and_reset(self) -> tuple[int, int]:
        """Return (keyboard_count, mouse_count) and reset counters to zero.

        mouse_count = clicks + move events (reduced resolution).
        """
        with self._lock:
            kb = self._keyboard_count
            mouse = self._mouse_click_count + (self._mouse_move_count // 10)
            self._keyboard_count = 0
            self._mouse_click_count = 0
            self._mouse_move_count = 0
        return kb, mouse

    @property
    def is_running(self) -> bool:
        """Whether the hook thread is currently running."""
        return self._running and self._hooks_installed
