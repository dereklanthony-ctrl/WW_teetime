"""
Notification Agent — reports scan results and booking outcomes.

Currently outputs to the console logger.  Designed to be extended
with SMS (Twilio), email, or webhook integrations later.
"""

from __future__ import annotations

import logging

from agents.booking import BookingResult
from models.tee_time import TeeTimeSlot

logger = logging.getLogger(__name__)


class NotificationAgent:
    """Sends notifications about tee-time events."""

    def notify_scan_results(self, matched: list[TeeTimeSlot]) -> None:
        if not matched:
            logger.info("Notification: no matching tee times found this scan.")
            return

        logger.info("Notification: %d matching slot(s) found:", len(matched))
        for i, slot in enumerate(matched, 1):
            logger.info("  %d. %s", i, slot)

    def notify_booking_result(self, result: BookingResult) -> None:
        if result.success:
            logger.info("Notification: BOOKING CONFIRMED — %s", result.message)
        else:
            logger.warning("Notification: booking failed — %s", result.message)

    def notify_block_detected(self) -> None:
        logger.error(
            "Notification: SECURITY BLOCK DETECTED. "
            "All automated activity has been paused. "
            "Please log in manually to verify your account status, "
            "then restart the agent."
        )

    def notify_error(self, context: str, error: Exception) -> None:
        logger.error("Notification: error during %s — %s: %s", context, type(error).__name__, error)
