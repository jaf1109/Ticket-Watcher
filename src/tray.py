"""System tray icon for the Ticket Watcher service.

Runs the background service with a tray icon showing status.
Right-click menu: Open Dashboard, Start/Stop, Quit.

Usage:
    pythonw src/tray.py
"""

from __future__ import annotations
import asyncio
import logging
import threading
import webbrowser
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("System tray requires: pip install pystray Pillow")
    print("Or run without tray: python src/service.py")
    sys.exit(1)

from src.service import main as run_service


logger = logging.getLogger("watcher.tray")

PORT = 5096


def create_icon_image(color: str = "#7c3aed") -> Image.Image:
    """Create a simple colored circle icon."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=color)
    # Draw a play triangle in the center
    cx, cy = size // 2, size // 2
    draw.polygon([
        (cx - 6, cy - 10),
        (cx - 6, cy + 10),
        (cx + 10, cy),
    ], fill="white")
    return img


def open_dashboard(_icon=None, _item=None):
    webbrowser.open(f"http://localhost:{PORT}")


def quit_app(icon, _item=None):
    icon.stop()


def run_tray():
    """Run the system tray icon in the main thread."""
    icon = pystray.Icon(
        "CineplexBD Watcher",
        icon=create_icon_image(),
        title="CineplexBD Ticket Watcher",
        menu=pystray.Menu(
            pystray.MenuItem("Open Dashboard", open_dashboard, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", quit_app),
        ),
    )

    # Run the async service in a background thread
    def run_async_service():
        asyncio.run(run_service(port=PORT))

    service_thread = threading.Thread(target=run_async_service, daemon=True)
    service_thread.start()

    # Show notification
    icon.run()


if __name__ == "__main__":
    run_tray()
