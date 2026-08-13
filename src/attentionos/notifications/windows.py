"""Best-effort Windows notification adapter."""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


class WindowsNotifier:
    """Show a basic Windows toast when available.

    This adapter intentionally falls back silently. The in-app notification
    record is the source of truth; OS toast delivery is best-effort.
    """

    def show(self, title: str, body: str) -> bool:
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType = WindowsRuntime] > $null; "
            "$template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02; "
            "$xml = [Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent($template); "
            "$texts = $xml.GetElementsByTagName('text'); "
            f"$texts.Item(0).AppendChild($xml.CreateTextNode('{_escape(title)}')) > $null; "
            f"$texts.Item(1).AppendChild($xml.CreateTextNode('{_escape(body)}')) > $null; "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AttentionOS').Show($toast);"
        )
        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if completed.returncode != 0:
                logger.debug("Windows toast failed: %s", completed.stderr)
                return False
            return True
        except Exception:
            logger.exception("Could not show Windows notification.")
            return False


def _escape(value: str) -> str:
    return value.replace("'", "''")
