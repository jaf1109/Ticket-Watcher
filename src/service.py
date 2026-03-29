"""Background service — runs dashboard + auto-starts monitor.

Usage:
    python src/service.py              Run with console output
    pythonw src/service.py             Run windowless (no console)
    python src/service.py --port 9090  Custom port
"""

from __future__ import annotations
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env if present
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from aiohttp import web
from src.config_loader import load_config
from src.web_server import WatcherHub, create_app


DATA_DIR = Path(__file__).parent.parent / "data"
PID_PATH = DATA_DIR / "watcher.pid"


def setup_logging() -> None:
    log_path = Path(__file__).parent.parent / "watcher.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(str(log_path), encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def write_pid() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()))


def remove_pid() -> None:
    try:
        PID_PATH.unlink(missing_ok=True)
    except Exception:
        pass


async def main(port: int = 8080) -> None:
    setup_logging()
    logger = logging.getLogger("watcher.service")

    config = load_config()
    hub = WatcherHub(config)
    app = create_app(hub)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    write_pid()
    logger.info(f"Dashboard running at http://localhost:{port}")

    # Auto-start monitor if configured
    if config.movie.id and config.cinema.location_id:
        logger.info(f"Auto-starting monitor: {config.movie.name} at {config.cinema.location}")
        await hub.start()
    else:
        logger.info("No movie/location configured. Open the dashboard to configure.")

    # Wait for shutdown signal
    stop = asyncio.Event()

    def handle_signal(*_):
        stop.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    await stop.wait()

    logger.info("Shutting down...")
    await hub.close()
    await runner.cleanup()
    remove_pid()
    logger.info("Service stopped.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CineplexBD Ticket Watcher Service")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    args = parser.parse_args()

    asyncio.run(main(port=args.port))
