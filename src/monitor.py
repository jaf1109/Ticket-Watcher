"""Main monitoring loop — checks for new show dates and alerts."""

from __future__ import annotations
import asyncio
import json
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from .api_client import CineplexAPI, APIError
from .config_loader import Config
from .notifier import Notifier

logger = logging.getLogger("watcher.monitor")

DATA_DIR = Path(__file__).parent.parent / "data"
STATE_PATH = DATA_DIR / "state.json"


def load_state() -> dict:
    """Load persisted watcher state from disk."""
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load state, starting fresh: {e}")
    return {"previous_dates": [], "last_check": None}


def save_state(state: dict) -> None:
    """Persist watcher state to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


async def run_monitor(
    config: Config,
    on_event: Callable[[dict], Awaitable[None]] | None = None,
    stop_event: asyncio.Event | None = None,
    api: CineplexAPI | None = None,
    run_once: bool = False,
) -> None:
    """Main monitoring loop.

    Args:
        config: Watcher configuration.
        on_event: Optional async callback for each event (used by dashboard).
        stop_event: Optional event to signal shutdown (used by dashboard).
        api: Optional shared API instance (used by dashboard to avoid duplicate auth).
    """
    movie_id = config.movie.id
    location_id = config.cinema.location_id

    if not movie_id or not location_id:
        print("ERROR: Movie ID and Location ID must be set in config.yaml")
        print("Run 'python main.py setup' first.")
        return

    owns_api = api is None
    api = api or CineplexAPI()
    notifier = Notifier.from_config(config)
    state = load_state()

    # Migrate old state format
    if "known_dates" in state and "previous_dates" not in state:
        state["previous_dates"] = []
        del state["known_dates"]
        save_state(state)

    _stop = stop_event or asyncio.Event()
    interval = max(config.monitoring.interval_seconds, 30)
    max_errors = config.monitoring.max_consecutive_errors
    consecutive_errors = 0
    check_count = 0

    async def emit(event: dict) -> None:
        """Emit event to callback and print to console."""
        if on_event:
            await on_event(event)

    # Only register signal handler if no external stop_event (CLI mode)
    if stop_event is None:
        def handle_signal(*_):
            _stop.set()
            print("\nShutting down gracefully...")
        signal.signal(signal.SIGINT, handle_signal)

    movie_name = config.movie.name or str(movie_id)
    location_name = config.cinema.location or str(location_id)

    print(f"Movie:    {movie_name} (ID: {movie_id})")
    print(f"Location: {location_name} (ID: {location_id})")
    print(f"Interval: {interval}s | Previously seen dates: {len(state['previous_dates'])}")
    print(f"Press Ctrl+C to stop.\n")

    await emit({
        "type": "status",
        "running": True,
        "movie": movie_name,
        "location": location_name,
        "interval": interval,
        "previous_dates": state["previous_dates"],
    })

    start_time = datetime.now(timezone.utc)
    max_seconds = config.monitoring.max_duration_minutes * 60 if config.monitoring.max_duration_minutes > 0 else 0

    while not _stop.is_set():
        check_count += 1
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%H:%M:%S")

        if max_seconds > 0 and (now - start_time).total_seconds() >= max_seconds:
            print(f"[{timestamp}] Max duration reached. Stopping.")
            await emit({"type": "stopped", "reason": "Max duration reached"})
            break

        try:
            print(f"[{timestamp}] Check #{check_count}...", end=" ", flush=True)
            current_dates = await api.get_movie_dates(location_id, movie_id)
            consecutive_errors = 0

            previous = set(state["previous_dates"])
            current = set(current_dates)
            new_dates = sorted(current - previous)
            removed_dates = sorted(previous - current)

            if not previous:
                print(f"Initial scan: {len(current_dates)} dates available: {current_dates}")
                await emit({
                    "type": "check",
                    "count": check_count,
                    "dates": sorted(current),
                    "new_dates": [],
                    "removed_dates": [],
                    "timestamp": timestamp,
                    "initial": True,
                })
            elif new_dates:
                msg = (
                    f"New screening dates for {movie_name}!\n"
                    f"New dates: {', '.join(new_dates)}\n"
                    f"All available: {', '.join(sorted(current))}\n"
                    f"Location: {location_name}"
                )
                print(f"NEW DATES FOUND: {new_dates}")
                await notifier.notify_all(msg)
                await emit({
                    "type": "alert",
                    "count": check_count,
                    "dates": sorted(current),
                    "new_dates": new_dates,
                    "removed_dates": removed_dates,
                    "message": msg,
                    "timestamp": timestamp,
                })
            else:
                print(f"No new dates. ({len(current_dates)} available)")
                await emit({
                    "type": "check",
                    "count": check_count,
                    "dates": sorted(current),
                    "new_dates": [],
                    "removed_dates": removed_dates,
                    "timestamp": timestamp,
                })

            if removed_dates:
                logger.info(f"Dates no longer available: {removed_dates}")

            state["previous_dates"] = sorted(current)
            state["last_check"] = now.isoformat()
            save_state(state)

        except APIError as e:
            consecutive_errors += 1
            print(f"API error ({consecutive_errors}/{max_errors}): {e}")
            await emit({
                "type": "error",
                "message": str(e),
                "consecutive": consecutive_errors,
                "timestamp": timestamp,
            })

            if consecutive_errors >= max_errors:
                if config.monitoring.fallback_to_browser:
                    print("Switching to browser fallback...")
                    try:
                        from .browser_fallback import browser_check_dates
                        current_dates = await browser_check_dates(config)
                        consecutive_errors = 0

                        previous = set(state["previous_dates"])
                        current = set(current_dates)
                        new_dates = sorted(current - previous)
                        if new_dates:
                            msg = (
                                f"New screening dates (via fallback)!\n"
                                f"New dates: {', '.join(new_dates)}\n"
                                f"All available: {', '.join(sorted(current))}\n"
                                f"Location: {location_name}"
                            )
                            print(f"NEW DATES (fallback): {new_dates}")
                            await notifier.notify_all(msg)
                            await emit({
                                "type": "alert",
                                "count": check_count,
                                "dates": sorted(current),
                                "new_dates": new_dates,
                                "message": msg,
                                "timestamp": timestamp,
                                "fallback": True,
                            })
                        state["previous_dates"] = sorted(current)
                        save_state(state)
                    except Exception as fb_err:
                        print(f"Browser fallback also failed: {fb_err}")
                        await notifier.notify_all(f"Ticket watcher stopped: too many errors.\nLast: {e}")
                        await emit({"type": "stopped", "reason": f"Too many errors: {e}"})
                        break
                else:
                    await notifier.notify_all(f"Ticket watcher stopped after {consecutive_errors} errors.\nLast: {e}")
                    await emit({"type": "stopped", "reason": f"Too many errors: {e}"})
                    break

        except Exception as e:
            consecutive_errors += 1
            print(f"Unexpected error ({consecutive_errors}): {e}")
            logger.exception("Unexpected error in monitor loop")
            await emit({
                "type": "error",
                "message": str(e),
                "consecutive": consecutive_errors,
                "timestamp": timestamp,
            })

        if not _stop.is_set():
            if run_once:
                break
            try:
                await asyncio.wait_for(_stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass  # Normal — interval elapsed, continue loop

    if owns_api:
        await api.close()
    save_state(state)
    await emit({"type": "stopped", "reason": "Shutdown"})
    print(f"\nStopped after {check_count} checks. State saved.")
