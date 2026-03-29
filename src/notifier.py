"""Notification dispatch: desktop toast + sound + Telegram."""

from __future__ import annotations
import logging
import sys
import webbrowser

import httpx

# Platform-specific imports (graceful fallback on non-Windows)
try:
    import winsound
except ImportError:
    winsound = None  # type: ignore[assignment]

logger = logging.getLogger("watcher.notify")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


async def send_telegram(bot_token: str, chat_id: str, message: str) -> bool:
    """Send a Telegram message. Returns True on success."""
    if not bot_token or not chat_id:
        logger.warning("Telegram not configured (missing bot_token or chat_id)")
        return False

    url = TELEGRAM_API.format(token=bot_token)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            })
            if resp.status_code == 200:
                logger.info("Telegram notification sent")
                return True
            else:
                logger.error(f"Telegram API returned {resp.status_code}: {resp.text}")
                return False
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def send_desktop_notification(title: str, message: str) -> bool:
    """Show a Windows 11 toast notification."""
    try:
        from winotify import Notification
        toast = Notification(
            app_id="CineplexBD Ticket Watcher",
            title=title,
            msg=message,
            duration="long",
        )
        toast.add_actions(label="Open CineplexBD", launch="https://www.cineplexbd.com/")
        toast.show()
        logger.info("Desktop notification sent")
        return True
    except ImportError:
        logger.warning("winotify not installed — skipping desktop notification")
        return False
    except Exception as e:
        logger.error(f"Desktop notification failed: {e}")
        return False


def play_alert_sound() -> None:
    """Play an alert sound (Windows only, no-op on other platforms)."""
    if not winsound:
        return
    try:
        from pathlib import Path
        sound_file = Path(__file__).parent.parent / "sounds" / "alert.wav"
        if sound_file.exists():
            winsound.PlaySound(str(sound_file), winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception as e:
        logger.warning(f"Could not play sound: {e}")


def open_browser(url: str = "https://www.cineplexbd.com/") -> None:
    """Open the cinema site in the default browser."""
    try:
        webbrowser.open(url)
    except Exception as e:
        logger.warning(f"Could not open browser: {e}")


class Notifier:
    """Dispatches notifications to all enabled channels."""

    def __init__(
        self,
        desktop_enabled: bool = True,
        telegram_enabled: bool = False,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        open_browser_on_alert: bool = True,
    ):
        self.desktop_enabled = desktop_enabled
        self.telegram_enabled = telegram_enabled
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.open_browser_on_alert = open_browser_on_alert

    @classmethod
    def from_config(cls, config) -> Notifier:
        """Create a Notifier from a Config object."""
        return cls(
            desktop_enabled=config.notifications.desktop.enabled,
            telegram_enabled=config.notifications.telegram.enabled,
            telegram_token=config.notifications.telegram.bot_token,
            telegram_chat_id=config.notifications.telegram.chat_id,
        )

    async def notify_all(self, message: str, title: str = "New Tickets Available!") -> None:
        """Send notification to all enabled channels."""
        logger.info(f"ALERT: {title} - {message}")

        if self.desktop_enabled:
            send_desktop_notification(title, message)
            play_alert_sound()

        if self.telegram_enabled:
            telegram_msg = f"<b>{title}</b>\n\n{message}"
            await send_telegram(self.telegram_token, self.telegram_chat_id, telegram_msg)

        if self.open_browser_on_alert:
            open_browser()
