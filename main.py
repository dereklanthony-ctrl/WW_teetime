#!/usr/bin/env python3
"""
WW TeeTime — Automated tee time monitoring and booking for Westwood Golf Club.

Usage:
    python main.py              Run the agent loop (scan + book on schedule)
    python main.py --once       Run a single scan/book cycle then exit
    python main.py --dry-run    Scan only — show matches but do not book
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from config.settings import settings
from agents.orchestrator import Orchestrator


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet down noisy libraries
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def print_banner() -> None:
    print(
        "\n"
        "  ╔══════════════════════════════════════════╗\n"
        "  ║       WW TeeTime — Booking Agent         ║\n"
        "  ║  Westwood Golf Club · Houston, TX         ║\n"
        "  ╚══════════════════════════════════════════╝\n"
    )
    print(f"  Days       : {', '.join(settings.preferred_days_list)}")
    print(f"  Window     : {settings.preferred_time_start} – {settings.preferred_time_end}")
    print(f"  Players    : {settings.player_count}")
    print(f"  Scan every : {settings.min_scan_interval} min")
    print(f"  Max books  : {settings.max_daily_booking_attempts}/day")
    print()


def validate_settings() -> bool:
    """Ensure critical settings are present before starting."""
    ok = True
    if not settings.cho_username:
        logging.error("CHO_USERNAME is not set — add it to .env")
        ok = False
    if not settings.cho_password:
        logging.error("CHO_PASSWORD is not set — add it to .env")
        ok = False
    if not settings.cho_base_url:
        logging.error("CHO_BASE_URL is not set — add it to .env")
        ok = False
    return ok


async def run(once: bool = False, dry_run: bool = False) -> None:
    orchestrator = Orchestrator()

    if dry_run:
        logging.info("DRY-RUN mode — will scan but not book.")
        await orchestrator.browser.start()
        try:
            matched = await orchestrator.monitor.scan()
            orchestrator.notification.notify_scan_results(matched)
            if matched:
                logging.info("Dry-run: would attempt to book: %s", matched[0])
        finally:
            await orchestrator.browser.stop()
        return

    if once:
        await orchestrator.browser.start()
        try:
            await orchestrator.run_cycle()
        finally:
            await orchestrator.browser.stop()
        return

    await orchestrator.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="WW TeeTime booking agent")
    parser.add_argument("--once", action="store_true", help="Run one cycle then exit")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, do not book")
    args = parser.parse_args()

    setup_logging()
    print_banner()

    if not validate_settings():
        sys.exit(1)

    try:
        asyncio.run(run(once=args.once, dry_run=args.dry_run))
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
