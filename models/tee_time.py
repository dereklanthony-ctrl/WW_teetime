from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TeeTimeSlot:
    """Represents a single available tee time slot on the tee sheet."""

    date: datetime
    time_str: str            # e.g. "9:30 AM"
    available_spots: int     # how many open player slots
    course_name: str = ""    # e.g. "Westwood"
    hole_start: str = ""     # e.g. "1" or "10"
    raw_data: dict = field(default_factory=dict)  # preserve anything extra from the page

    @property
    def day_of_week(self) -> str:
        return self.date.strftime("%A").lower()

    @property
    def time_24h(self) -> str:
        """Convert display time to 24-hour HH:MM for comparison."""
        try:
            parsed = datetime.strptime(self.time_str.strip(), "%I:%M %p")
            return parsed.strftime("%H:%M")
        except ValueError:
            return self.time_str

    def __str__(self) -> str:
        return (
            f"{self.date.strftime('%a %m/%d')} {self.time_str} "
            f"({self.available_spots} open) [{self.course_name}]"
        )
