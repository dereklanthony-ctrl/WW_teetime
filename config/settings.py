from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- ClubHouse Online credentials ---
    cho_username: str = ""
    cho_password: str = ""
    cho_base_url: str = "https://westwoodgc.clubhouseonline-e3.com"

    # --- Booking preferences ---
    preferred_days: str = "saturday,sunday"
    preferred_time_start: str = "09:00"
    preferred_time_end: str = "11:30"
    player_count: int = 2

    # --- Safety / rate-limiting ---
    min_action_delay: float = Field(default=2.0, description="Min seconds between browser actions")
    min_scan_interval: int = Field(default=15, description="Min minutes between tee sheet scans")
    max_daily_booking_attempts: int = Field(default=5, description="Max booking attempts per day")
    max_login_attempts: int = Field(default=3, description="Max login tries before cooldown")
    login_cooldown_minutes: int = Field(default=30, description="Cooldown after max login failures")

    @property
    def preferred_days_list(self) -> list[str]:
        return [d.strip().lower() for d in self.preferred_days.split(",")]


settings = Settings()
