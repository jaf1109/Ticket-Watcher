"""Discover CineplexBD API endpoints by intercepting SPA network requests."""

from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, Response

from .models import APIContract, APIEndpoint

logger = logging.getLogger("watcher.discovery")

API_DOMAINS = ["cineplex-web-api.cineplexbd.com", "cineplex-ticket-api.cineplexbd.com"]
DATA_DIR = Path(__file__).parent.parent / "data"


async def _capture_response(response: Response, captured: list[dict]) -> None:
    """Capture API responses from CineplexBD backends."""
    url = response.url
    if not any(domain in url for domain in API_DOMAINS):
        return

    try:
        request = response.request
        body = None
        try:
            body = await response.json()
        except Exception:
            pass

        entry = {
            "url": url,
            "method": request.method,
            "request_headers": dict(request.headers),
            "request_body": request.post_data,
            "status": response.status,
            "response_body": body,
        }
        captured.append(entry)
        logger.info(f"Captured: {request.method} {url} -> {response.status}")
    except Exception as e:
        logger.warning(f"Failed to capture response for {url}: {e}")


async def run_discovery(headless: bool = False) -> list[dict]:
    """Launch browser, navigate CineplexBD, and capture all API calls.

    Args:
        headless: Run browser in headless mode. Set False to watch it navigate.

    Returns:
        List of captured API call dicts.
    """
    captured: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # Attach response listener
        page.on("response", lambda resp: asyncio.ensure_future(_capture_response(resp, captured)))

        # --- Phase 1: Main site (movie listings, showtimes) ---
        print("\n[Discovery] Loading main site...")
        await page.goto("https://www.cineplexbd.com/", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        print("[Discovery] Navigating to movie list...")
        await page.goto("https://www.cineplexbd.com/movie-list", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # Try clicking on the first movie to trigger detail/showtime calls
        try:
            movie_links = await page.query_selector_all("a[href*='movie']")
            if movie_links:
                # Click a movie card to trigger showtime API calls
                for link in movie_links[:3]:
                    href = await link.get_attribute("href")
                    if href and "/movie-list" not in href and "/movie-search" not in href:
                        print(f"[Discovery] Clicking movie link: {href}")
                        await link.click()
                        await page.wait_for_load_state("networkidle", timeout=15000)
                        await page.wait_for_timeout(2000)
                        break
        except Exception as e:
            logger.warning(f"Could not click movie link: {e}")

        # Navigate to showtime page
        print("[Discovery] Navigating to showtime page...")
        await page.goto("https://www.cineplexbd.com/show-time", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # Also try the movie-show-time route
        await page.goto("https://www.cineplexbd.com/movie-show-time", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # --- Phase 2: Ticket site ---
        print("[Discovery] Loading ticket site...")
        await page.goto("https://ticket.cineplexbd.com/", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # Try navigating to booking-related pages
        for route in ["/get-shows", "/get-showdate", "/booking"]:
            try:
                await page.goto(f"https://ticket.cineplexbd.com{route}", wait_until="networkidle", timeout=15000)
                await page.wait_for_timeout(2000)
            except Exception:
                pass

        await browser.close()

    print(f"\n[Discovery] Captured {len(captured)} API calls.")
    return captured


def _classify_endpoint(entry: dict) -> str:
    """Guess the purpose of an API endpoint based on its URL and response."""
    url = entry["url"].lower()
    body = entry.get("response_body")

    if "movie" in url and "show" not in url:
        return "get_movies"
    if "cinema" in url or "theater" in url or "hall" in url:
        return "get_cinemas"
    if "location" in url or "city" in url or "area" in url:
        return "get_locations"
    if "showdate" in url or "show-date" in url or "show_date" in url:
        return "get_show_dates"
    if "showtime" in url or "show-time" in url or "show_time" in url:
        return "get_showtimes"
    if "show" in url:
        return "get_shows"
    if "seat" in url:
        return "get_seats"
    if "banner" in url or "slider" in url:
        return "get_banners"
    if "setting" in url or "config" in url:
        return "get_settings"

    # Generic fallback based on response structure
    if isinstance(body, dict):
        data = body.get("data", body)
        if isinstance(data, list) and data:
            first = data[0] if isinstance(data[0], dict) else {}
            if "movie" in str(first.keys()).lower():
                return "get_movies"
            if "cinema" in str(first.keys()).lower():
                return "get_cinemas"

    return f"unknown_{url.split('/')[-1][:30]}"


def save_contract(captured: list[dict]) -> APIContract:
    """Classify captured calls and save as an API contract."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    contract = APIContract(
        discovered_at=datetime.now(timezone.utc).isoformat(),
    )

    for entry in captured:
        purpose = _classify_endpoint(entry)

        # If we already have this purpose, append a number
        base_purpose = purpose
        counter = 2
        while purpose in contract.endpoints:
            purpose = f"{base_purpose}_{counter}"
            counter += 1

        contract.endpoints[purpose] = APIEndpoint(
            url=entry["url"],
            method=entry["method"],
            headers={
                k: v for k, v in entry["request_headers"].items()
                if k.lower() in ("content-type", "accept", "authorization", "origin", "referer")
            },
            body=json.loads(entry["request_body"]) if entry.get("request_body") else None,
            purpose=purpose,
        )

    # Save contract
    contract_path = DATA_DIR / "api_contract.json"
    with open(contract_path, "w", encoding="utf-8") as f:
        json.dump(contract.model_dump(), f, indent=2, default=str)

    print(f"[Discovery] Saved API contract with {len(contract.endpoints)} endpoints to {contract_path}")

    # Also save raw captured data for debugging
    raw_path = DATA_DIR / "raw_captures.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(captured, f, indent=2, default=str)

    print(f"[Discovery] Saved raw captures to {raw_path}")

    return contract


def print_captured_summary(captured: list[dict]) -> None:
    """Print a human-readable summary of captured API calls."""
    if not captured:
        print("\nNo API calls captured. The site may need manual interaction.")
        print("Try running with --visible flag to see the browser.")
        return

    print(f"\n{'='*70}")
    print(f"  Captured {len(captured)} API calls")
    print(f"{'='*70}")

    for i, entry in enumerate(captured, 1):
        url = entry["url"]
        method = entry["method"]
        status = entry["status"]
        purpose = _classify_endpoint(entry)
        body = entry.get("response_body")

        print(f"\n  [{i}] {method} {url}")
        print(f"      Status: {status} | Purpose: {purpose}")

        if entry.get("request_body"):
            try:
                req_body = json.loads(entry["request_body"])
                print(f"      Request body: {json.dumps(req_body, indent=8)[:200]}")
            except (json.JSONDecodeError, TypeError):
                print(f"      Request body: {str(entry['request_body'])[:200]}")

        if isinstance(body, dict):
            data = body.get("data", body)
            if isinstance(data, list):
                print(f"      Response: list of {len(data)} items")
                if data and isinstance(data[0], dict):
                    print(f"      First item keys: {list(data[0].keys())[:8]}")
            else:
                print(f"      Response keys: {list(body.keys())[:8]}")

    print(f"\n{'='*70}")


async def discover_and_save(headless: bool = False) -> APIContract:
    """Full discovery pipeline: capture, classify, save."""
    captured = await run_discovery(headless=headless)
    print_captured_summary(captured)
    contract = save_contract(captured)
    return contract
