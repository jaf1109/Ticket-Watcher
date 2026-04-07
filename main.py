"""CineplexBD Ticket Watcher — CLI Entry Point.

Usage:
    python main.py discover [--visible]   Debug: discover API endpoints with browser
    python main.py list-locations         Show available cinema locations
    python main.py list-movies [LOC_ID]   Show movies at a location (default: 1)
    python main.py setup                  Interactive: pick location & movie
    python main.py watch                  Start monitoring for new dates
    python main.py dashboard [--port N]   Launch web dashboard
    python main.py test-notify            Test desktop + Telegram notifications
    python main.py status                 Show current config & state
"""

from __future__ import annotations
import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

# Load .env if present (before any other imports that read env vars)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from src.config_loader import load_config, save_config


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("watcher.log", encoding="utf-8"),
        ],
    )


async def cmd_discover(args) -> None:
    """Run API discovery with Playwright (for debugging)."""
    from src.discovery import discover_and_save

    print("Starting API discovery (debug mode)...")
    print("This opens a browser to capture API calls.\n")
    headless = not args.visible
    await discover_and_save(headless=headless)


async def cmd_list_locations(args) -> None:
    """List available cinema locations."""
    from src.api_client import CineplexAPI

    api = CineplexAPI()
    try:
        locations = await api.get_locations()
        if not locations:
            print("No locations found.")
            return

        print(f"\nCineplexBD Locations ({len(locations)}):\n")
        for loc in locations:
            title = loc.get("locationTitle") or loc.get("location_name", "Unknown")
            print(f"  [{loc['id']}] {title}")
            address = loc.get("address", "")
            if address:
                import re
                clean = re.sub(r"<[^>]+>", " ", address).strip()
                print(f"      {clean}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await api.close()


async def cmd_list_movies(args) -> None:
    """List movies at a location."""
    from src.api_client import CineplexAPI

    api = CineplexAPI()
    try:
        loc_id = args.location_id or 1
        data = await api.get_movies(loc_id)

        running = data.get("running", [])
        upcoming = data.get("upcoming", [])

        if running:
            print(f"\nNow Showing ({len(running)}):\n")
            for m in running:
                print(f"  [{m['movie_id']}] {m['title']}")
                print(f"      {m.get('genre', '')} | {m.get('language', '')} | {m.get('category', '')}")
                print(f"      Cast: {m.get('actor', 'N/A')}")
                print()

        if upcoming:
            print(f"Coming Soon ({len(upcoming)}):\n")
            for m in upcoming:
                print(f"  [{m['movie_id']}] {m['title']}")
                print(f"      {m.get('genre', '')} | {m.get('language', '')} | Release: {m.get('release', 'TBA')}")
                print()

        if not running and not upcoming:
            print("No movies found for this location.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await api.close()


async def cmd_setup(args) -> None:
    """Interactive setup: pick location and movie."""
    from src.api_client import CineplexAPI

    config = load_config()
    api = CineplexAPI()

    try:
        # Step 1: Pick location
        print("Fetching locations...")
        locations = await api.get_locations()
        if not locations:
            print("No locations found.")
            return

        print(f"\nAvailable locations ({len(locations)}):\n")
        for i, loc in enumerate(locations, 1):
            title = loc.get("locationTitle") or loc.get("location_name", "Unknown")
            print(f"  {i:2d}. [{loc['id']}] {title}")

        while True:
            try:
                choice = int(input(f"\nSelect location (1-{len(locations)}): "))
                if 1 <= choice <= len(locations):
                    selected_loc = locations[choice - 1]
                    break
            except (ValueError, EOFError):
                pass
            print("Invalid choice, try again.")

        loc_title = selected_loc.get("locationTitle") or selected_loc.get("location_name", "")
        config.cinema.location = loc_title
        config.cinema.location_id = selected_loc["id"]
        print(f"Selected location: {loc_title}")

        # Step 2: Pick movie
        print("\nFetching movies...")
        data = await api.get_movies(selected_loc["id"])
        running = data.get("running", [])
        upcoming = data.get("upcoming", [])
        all_movies = running + upcoming

        if not all_movies:
            print("No movies found at this location.")
            return

        print(f"\nAvailable movies ({len(all_movies)}):\n")
        for i, m in enumerate(all_movies, 1):
            status = "NOW SHOWING" if m in running else "COMING SOON"
            print(f"  {i:2d}. {m['title']} [{status}]")
            print(f"      {m.get('genre', '')} | {m.get('language', '')}")

        while True:
            try:
                choice = int(input(f"\nSelect movie (1-{len(all_movies)}): "))
                if 1 <= choice <= len(all_movies):
                    selected_movie = all_movies[choice - 1]
                    break
            except (ValueError, EOFError):
                pass
            print("Invalid choice, try again.")

        config.movie.name = selected_movie["title"]
        config.movie.id = selected_movie["movie_id"]
        print(f"Selected movie: {selected_movie['title']} (ID: {selected_movie['movie_id']})")

        # Step 3: Quick test — show current showtimes
        print("\nChecking current showtimes...")
        dates = await api.get_movie_dates(selected_loc["id"], selected_movie["movie_id"])
        if dates:
            print(f"Currently showing on: {', '.join(dates)}")
        else:
            print("No showtimes yet — the watcher will alert you when dates appear!")

        # Save
        save_config(config)
        print(f"\nConfig saved to config.yaml!")
        print(f"Run 'python main.py watch' to start monitoring.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await api.close()


async def cmd_watch(args) -> None:
    """Start the monitoring loop."""
    from src.monitor import run_monitor

    config = load_config()

    if not config.movie.id or not config.cinema.location_id:
        print("Movie and location not configured yet.")
        print("Run 'python main.py setup' first.")
        return

    print("CineplexBD Ticket Watcher")
    print("=" * 40)
    await run_monitor(config, run_once=args.once)


async def cmd_test_notify(args) -> None:
    """Send test notifications."""
    from src.notifier import Notifier

    config = load_config()
    notifier = Notifier.from_config(config)

    movie = config.movie.name or f"ID: {config.movie.id}"
    location = config.cinema.location or f"ID: {config.cinema.location_id}"

    print("Sending test notifications...")
    await notifier.notify_all(
        message=f"This is a test from CineplexBD Ticket Watcher!\nIf you see this, notifications are working.\n\nWatching: {movie}\nLocation: {location}",
        title="Test Notification",
    )
    print("Done! Check your desktop and Telegram.")


async def cmd_dashboard(args) -> None:
    """Launch the web dashboard."""
    import webbrowser
    from aiohttp import web
    from src.web_server import WatcherHub, create_app

    config = load_config()
    hub = WatcherHub(config)
    app = create_app(hub)

    port = args.port or 5096
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", port)
    await site.start()

    url = f"http://localhost:{port}"
    print(f"Dashboard running at {url}")
    print("Press Ctrl+C to stop.\n")

    if not args.no_browser:
        webbrowser.open(url)

    stop = asyncio.Event()

    def handle_signal(*_):
        stop.set()
        print("\nShutting down...")

    signal.signal(signal.SIGINT, handle_signal)
    await stop.wait()

    if hub.running:
        await hub.stop()
    await runner.cleanup()


async def cmd_status(args) -> None:
    """Show current watcher status."""
    config = load_config()

    print("CineplexBD Ticket Watcher — Status")
    print("=" * 40)
    print(f"Movie:    {config.movie.name or 'Not set'} (ID: {config.movie.id})")
    print(f"Location: {config.cinema.location or 'Not set'} (ID: {config.cinema.location_id})")
    print(f"Interval: {config.monitoring.interval_seconds}s")
    print(f"Desktop:  {'ON' if config.notifications.desktop.enabled else 'OFF'}")
    print(f"Telegram: {'ON' if config.notifications.telegram.enabled else 'OFF'}")

    state_path = Path("data/state.json")
    if state_path.exists():
        with open(state_path, "r") as f:
            state = json.load(f)
        known = state.get("previous_dates", state.get("known_dates", []))
        print(f"\nAvailable dates: {len(known)}")
        for d in sorted(known):
            print(f"  - {d}")
        print(f"Last check: {state.get('last_check', 'never')}")
    else:
        print("\nNo state yet (haven't run watch)")


def main():
    parser = argparse.ArgumentParser(
        description="CineplexBD Ticket Watcher Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  list-locations  Show cinema locations
  list-movies     Show movies at a location
  setup           Interactive: pick location & movie
  watch           Start monitoring for new dates
  test-notify     Test notifications (desktop + Telegram)
  status          Show current config and state
  discover        Debug: capture API calls with browser
        """,
    )
    sub = parser.add_subparsers(dest="command")

    p_discover = sub.add_parser("discover", help="Debug: discover API endpoints")
    p_discover.add_argument("--visible", action="store_true", help="Show browser window")

    sub.add_parser("list-locations", help="List cinema locations")

    p_movies = sub.add_parser("list-movies", help="List movies")
    p_movies.add_argument("location_id", nargs="?", type=int, default=None, help="Location ID")

    sub.add_parser("setup", help="Interactive setup")
    p_watch = sub.add_parser("watch", help="Start monitoring")
    p_watch.add_argument("--once", action="store_true", help="Run a single check and exit (for CI/cron)")

    p_dash = sub.add_parser("dashboard", help="Launch web dashboard")
    p_dash.add_argument("--port", type=int, default=5096, help="Port (default: 5096)")
    p_dash.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")

    sub.add_parser("test-notify", help="Test notifications")
    sub.add_parser("status", help="Show status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    config = load_config()
    setup_logging(config.logging.level)

    commands = {
        "discover": cmd_discover,
        "list-locations": cmd_list_locations,
        "list-movies": cmd_list_movies,
        "setup": cmd_setup,
        "watch": cmd_watch,
        "dashboard": cmd_dashboard,
        "test-notify": cmd_test_notify,
        "status": cmd_status,
    }

    handler = commands.get(args.command)
    if handler:
        asyncio.run(handler(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
