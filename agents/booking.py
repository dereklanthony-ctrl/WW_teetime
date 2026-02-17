"""
Booking Agent — attempts to reserve the best matching tee time slot.

Responsibilities:
  - Receive candidate slots from the Monitor Agent
  - Enforce daily booking caps via the safety layer
  - Attempt to book the highest-priority slot first
  - Report success/failure back to the Orchestrator
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from browser.adapter import BrowserAdapter
from browser.safety import check_can_book, record_booking_attempt, get_state
from models.tee_time import TeeTimeSlot

logger = logging.getLogger(__name__)


@dataclass
class BookingResult:
    success: bool
    slot: TeeTimeSlot | None
    message: str


class BookingAgent:
    def __init__(self, browser: BrowserAdapter) -> None:
        self.browser = browser

    async def attempt(self, candidates: list[TeeTimeSlot]) -> BookingResult:
        """
        Try to book the first viable candidate.

        Iterates through candidates in priority order.  Stops on the first
        successful booking or when safety limits are reached.
        """
        if not candidates:
            return BookingResult(success=False, slot=None, message="No candidates to book.")

        if get_state().blocked:
            return BookingResult(
                success=False,
                slot=None,
                message="Booking skipped — security block is active.",
            )

        for slot in candidates:
            if not check_can_book():
                return BookingResult(
                    success=False,
                    slot=slot,
                    message="Daily booking attempt cap reached.",
                )

            logger.info("Booking Agent: attempting slot %s", slot)
            record_booking_attempt()

            success = await self.browser.book_slot(slot)
            if success:
                return BookingResult(
                    success=True,
                    slot=slot,
                    message=f"Booked: {slot}",
                )

            logger.warning("Booking Agent: slot %s failed — trying next candidate.", slot)

            if get_state().blocked:
                return BookingResult(
                    success=False,
                    slot=slot,
                    message="Booking halted — security block detected during attempt.",
                )

        return BookingResult(
            success=False,
            slot=None,
            message="All candidate slots failed to book.",
        )
