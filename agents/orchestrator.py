"""
Orchestrator — ties the Monitor, Booking, and Notification agents together
and runs them on a schedule.
"""

from __future__ import annotations

import asyncio
import logging

from browser.adapter import BrowserAdapter
from browser.safety import get_state, clear_block
from config.settings import settings
from models.rules import BookingRule, RuleSet

from agents.monitor import MonitorAgent
from agents.booking import BookingAgent
from agents.notification import NotificationAgent

logger = logging.getLogger(__name__)


class Orchestrator:
    """Coordinates scheduled scans, bookings, and notifications."""

    def __init__(self) -> None:
        self.browser = BrowserAdapter()
        self.rules = self._build_rules()
        self.monitor = MonitorAgent(self.browser, self.rules)
        self.booking = BookingAgent(self.browser)
        self.notification = NotificationAgent()
        self._running = False

    @staticmethod
    def _build_rules() -> RuleSet:
        """Build the RuleSet from application settings."""
        rule = BookingRule(
            allowed_days=settings.preferred_days_list,
            time_start=settings.preferred_time_start,
            time_end=settings.preferred_time_end,
            min_spots=settings.player_count,
            priority=1,
        )
        return RuleSet(rules=[rule])

    async def run_cycle(self) -> None:
        """Execute one full monitor-book-notify cycle."""
        state = get_state()

        # If the session was flagged dirty (post-block), rotate fingerprint
        if state.session_dirty and not state.blocked:
            await self.browser.rotate_session()

        if state.blocked:
            self.notification.notify_block_detected()
            logger.info("Orchestrator: cycle skipped due to active security block.")
            return

        logger.info("Orchestrator: starting scan cycle.")

        try:
            matched = await self.monitor.scan()
            self.notification.notify_scan_results(matched)

            if matched:
                result = await self.booking.attempt(matched)
                self.notification.notify_booking_result(result)
            else:
                logger.info("Orchestrator: no matching slots — nothing to book.")

        except Exception as exc:
            self.notification.notify_error("scan/book cycle", exc)

        # Re-check for blocks after the cycle
        if get_state().blocked:
            self.notification.notify_block_detected()

        logger.info("Orchestrator: cycle complete.")

    async def start(self) -> None:
        """
        Start the browser and run scan cycles on a repeating schedule.

        Loops until stopped or a block is detected.
        """
        logger.info("Orchestrator: starting up.")
        await self.browser.start()
        self._running = True

        try:
            while self._running:
                await self.run_cycle()

                state = get_state()
                if state.blocked:
                    if state.block_until > 0:
                        import time as _time
                        wait_secs = max(state.block_until - _time.time(), 60)
                        logger.warning(
                            "Orchestrator: block detected — waiting %.0f minutes "
                            "then retrying with a fresh session.",
                            wait_secs / 60,
                        )
                        await asyncio.sleep(wait_secs)
                        # After cooldown, the `blocked` property auto-clears
                        continue
                    else:
                        logger.error(
                            "Orchestrator: permanent block detected — shutting down. "
                            "Resolve the issue manually, then restart."
                        )
                        break

                interval = settings.min_scan_interval * 60
                logger.info(
                    "Orchestrator: sleeping %d minutes until next cycle.",
                    settings.min_scan_interval,
                )
                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            logger.info("Orchestrator: received cancellation — shutting down.")
        except KeyboardInterrupt:
            logger.info("Orchestrator: interrupted — shutting down.")
        finally:
            await self.browser.stop()
            self._running = False
            logger.info("Orchestrator: stopped.")

    def stop(self) -> None:
        self._running = False
