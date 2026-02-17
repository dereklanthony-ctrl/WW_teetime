"""
Monitor Agent — scans the tee sheet for available slots that match booking rules.

Responsibilities:
  - Determine which upcoming dates need scanning (next Saturday/Sunday)
  - Log in via the browser adapter
  - Fetch available tee times
  - Filter results through the RuleSet
  - Return matched slots for the Booking Agent
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from browser.adapter import BrowserAdapter
from browser.safety import check_scan_interval, record_scan, get_state
from config.settings import settings
from models.rules import RuleSet
from models.tee_time import TeeTimeSlot

logger = logging.getLogger(__name__)


class MonitorAgent:
    def __init__(self, browser: BrowserAdapter, rules: RuleSet) -> None:
        self.browser = browser
        self.rules = rules

    def _next_target_dates(self, days_ahead: int = 14) -> list[datetime]:
        """Return upcoming dates that match preferred days within the lookahead window."""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        targets: list[datetime] = []
        for offset in range(1, days_ahead + 1):
            candidate = today + timedelta(days=offset)
            if candidate.strftime("%A").lower() in settings.preferred_days_list:
                targets.append(candidate)
        return targets

    async def scan(self) -> list[TeeTimeSlot]:
        """
        Run a full scan cycle: login -> fetch tee times -> filter matches.

        Returns matched slots (may be empty).
        """
        if get_state().blocked:
            logger.error("Monitor: skipping scan — security block is active.")
            return []

        if not check_scan_interval():
            logger.info("Monitor: scan interval not met — skipping.")
            return []

        # Login (no-op if already authenticated)
        if not await self.browser.login():
            logger.error("Monitor: login failed — cannot scan.")
            return []

        target_dates = self._next_target_dates()
        if not target_dates:
            logger.info("Monitor: no target dates in the lookahead window.")
            return []

        logger.info(
            "Monitor: scanning %d date(s): %s",
            len(target_dates),
            ", ".join(d.strftime("%a %m/%d") for d in target_dates),
        )

        all_slots: list[TeeTimeSlot] = []
        for date in target_dates:
            slots = await self.browser.fetch_tee_times(date)
            all_slots.extend(slots)

            # Bail early if we got blocked mid-scan
            if get_state().blocked:
                logger.error("Monitor: block detected mid-scan — aborting remaining dates.")
                break

        matched = self.rules.all_matches(all_slots)
        logger.info(
            "Monitor: %d total slots found, %d match rules.",
            len(all_slots),
            len(matched),
        )
        return matched
