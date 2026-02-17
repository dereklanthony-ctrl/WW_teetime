from __future__ import annotations

from dataclasses import dataclass, field
from models.tee_time import TeeTimeSlot


@dataclass
class BookingRule:
    """A single rule that a tee time slot must satisfy to be auto-booked."""

    allowed_days: list[str] = field(default_factory=lambda: ["saturday", "sunday"])
    time_start: str = "09:00"   # 24h format
    time_end: str = "11:30"     # 24h format
    min_spots: int = 2          # slot must have at least this many openings
    priority: int = 1           # lower = higher priority (for ranking matches)

    def matches(self, slot: TeeTimeSlot) -> bool:
        if slot.day_of_week not in self.allowed_days:
            return False
        if not (self.time_start <= slot.time_24h <= self.time_end):
            return False
        if slot.available_spots < self.min_spots:
            return False
        return True


@dataclass
class RuleSet:
    """An ordered collection of booking rules.  First match wins."""

    rules: list[BookingRule] = field(default_factory=list)

    def best_match(self, slots: list[TeeTimeSlot]) -> TeeTimeSlot | None:
        """Return the best matching slot across all rules, or None."""
        for rule in sorted(self.rules, key=lambda r: r.priority):
            for slot in slots:
                if rule.matches(slot):
                    return slot
        return None

    def all_matches(self, slots: list[TeeTimeSlot]) -> list[TeeTimeSlot]:
        """Return all slots that match any rule, ordered by priority."""
        matched: list[TeeTimeSlot] = []
        for rule in sorted(self.rules, key=lambda r: r.priority):
            for slot in slots:
                if rule.matches(slot) and slot not in matched:
                    matched.append(slot)
        return matched
