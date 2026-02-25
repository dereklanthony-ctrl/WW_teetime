"""
Safety layer to prevent triggering anti-bot / cybersecurity protections.

Strategies:
  1. Rate limiting  — enforce minimum delays between all actions
  2. Human-like timing — randomize delays so patterns aren't machine-detectable
  3. Session reuse — persist browser state to avoid repeated logins
  4. Daily caps — hard limits on login and booking attempts
  5. Backoff — exponential backoff when errors are detected
  6. Block detection — recognize CAPTCHAs, WAF pages, and IP blocks early
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

from config.settings import settings

logger = logging.getLogger(__name__)

# Phrases that commonly appear on security-block pages
BLOCK_SIGNATURES = [
    "access denied",
    "403 forbidden",
    "rate limit",
    "too many requests",
    "captcha",
    "verify you are human",
    "bot detection",
    "unusual activity",
    "temporarily blocked",
    "security check",
    "cloudflare",
    "please wait while we verify",
    "automated access",
]


@dataclass
class SafetyState:
    """Tracks counters and timestamps for the safety layer."""

    login_attempts_today: int = 0
    booking_attempts_today: int = 0
    last_action_time: float = 0.0
    last_scan_time: float = 0.0
    consecutive_errors: int = 0
    is_in_cooldown: bool = False
    cooldown_until: float = 0.0
    current_date: str = ""  # reset counters daily
    _blocked: bool = False
    block_count: int = 0         # how many times we've been blocked today
    block_until: float = 0.0     # graduated cooldown timestamp
    session_dirty: bool = False  # True = should clear cookies & rotate UA

    daily_counters_reset_fields: list[str] = field(
        default_factory=lambda: ["login_attempts_today", "booking_attempts_today"],
        repr=False,
    )

    def _maybe_reset_daily(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if self.current_date != today:
            self.current_date = today
            self.login_attempts_today = 0
            self.booking_attempts_today = 0
            self.consecutive_errors = 0
            self._blocked = False
            self.block_count = 0
            self.block_until = 0.0
            self.session_dirty = False
            logger.info("Daily safety counters reset.")

    @property
    def blocked(self) -> bool:
        # Auto-unblock after graduated cooldown expires
        if self._blocked and self.block_until and time.time() >= self.block_until:
            logger.info("Safety: block cooldown expired — resuming operations.")
            self._blocked = False
            self.session_dirty = True  # signal adapter to reset session
        return self._blocked


# Module-level singleton
_state = SafetyState()


def get_state() -> SafetyState:
    _state._maybe_reset_daily()
    return _state


async def human_delay(action_label: str = "action") -> None:
    """Sleep for a randomized, human-like interval between browser actions."""
    base = settings.min_action_delay
    jitter = random.uniform(0, base)  # 0 – 100% extra
    delay = base + jitter
    logger.debug("Safety: waiting %.1fs before %s", delay, action_label)
    await asyncio.sleep(delay)


async def backoff_delay(attempt: int, action_label: str = "retry") -> None:
    """Exponential backoff: 2^attempt seconds, capped at 5 minutes, plus jitter."""
    base = min(2 ** attempt, 300)
    jitter = random.uniform(0, base * 0.3)
    delay = base + jitter
    logger.warning("Safety: backoff %.1fs before %s (attempt %d)", delay, action_label, attempt)
    await asyncio.sleep(delay)


def check_can_login() -> bool:
    """Return True if a login attempt is allowed right now."""
    state = get_state()
    now = time.time()

    if state.is_in_cooldown and now < state.cooldown_until:
        remaining = int(state.cooldown_until - now)
        logger.warning(
            "Safety: login cooldown active — %d seconds remaining.", remaining
        )
        return False

    if state.is_in_cooldown and now >= state.cooldown_until:
        logger.info("Safety: login cooldown expired, resetting.")
        state.is_in_cooldown = False
        state.login_attempts_today = 0

    if state.login_attempts_today >= settings.max_login_attempts:
        state.is_in_cooldown = True
        state.cooldown_until = now + settings.login_cooldown_minutes * 60
        logger.warning(
            "Safety: max login attempts (%d) reached — entering %d-min cooldown.",
            settings.max_login_attempts,
            settings.login_cooldown_minutes,
        )
        return False

    return True


def record_login_attempt(success: bool) -> None:
    state = get_state()
    state.login_attempts_today += 1
    if success:
        state.consecutive_errors = 0
        logger.info("Safety: login succeeded (attempt %d today).", state.login_attempts_today)
    else:
        state.consecutive_errors += 1
        logger.warning(
            "Safety: login failed (attempt %d today, %d consecutive errors).",
            state.login_attempts_today,
            state.consecutive_errors,
        )


def check_can_book() -> bool:
    state = get_state()
    if state.booking_attempts_today >= settings.max_daily_booking_attempts:
        logger.warning(
            "Safety: daily booking cap (%d) reached — no more attempts today.",
            settings.max_daily_booking_attempts,
        )
        return False
    return True


def record_booking_attempt() -> None:
    state = get_state()
    state.booking_attempts_today += 1
    logger.info("Safety: booking attempt %d today.", state.booking_attempts_today)


def check_scan_interval() -> bool:
    """Return True if enough time has passed since the last scan."""
    state = get_state()
    now = time.time()
    elapsed = now - state.last_scan_time
    min_gap = settings.min_scan_interval * 60
    if elapsed < min_gap:
        logger.debug(
            "Safety: only %ds since last scan (min %ds) — skipping.",
            int(elapsed),
            int(min_gap),
        )
        return False
    return True


def record_scan() -> None:
    get_state().last_scan_time = time.time()


def detect_block(page_content: str) -> bool:
    """Scan page text for signs that we've been blocked or challenged.

    Uses a graduated cooldown: 5 min → 15 min → 30 min → 60 min on
    repeated blocks.  After the cooldown, the adapter should rotate its
    fingerprint (clear cookies, pick new UA/viewport).
    """
    lower = page_content.lower()
    for sig in BLOCK_SIGNATURES:
        if sig in lower:
            state = get_state()
            state.block_count += 1
            # Graduated cooldown: 5, 15, 30, 60 minutes
            cooldown_minutes = min(5 * (2 ** (state.block_count - 1)), 60)
            state.block_until = time.time() + cooldown_minutes * 60
            state._blocked = True
            state.session_dirty = True
            logger.error(
                "Safety: BLOCK DETECTED (signature='%s', block #%d today). "
                "Cooling down for %d minutes.",
                sig,
                state.block_count,
                cooldown_minutes,
            )
            return True
    return False


def clear_block() -> None:
    state = get_state()
    state._blocked = False
    state.block_until = 0.0
