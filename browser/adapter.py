"""
Browser adapter — wraps Playwright to interact with the ClubHouse Online portal.

All page interactions go through the safety layer so we never exceed rate
limits or trigger anti-bot protections.
"""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from browser.safety import (
    human_delay,
    backoff_delay,
    detect_block,
    check_can_login,
    record_login_attempt,
    get_state,
)
from browser.stealth import apply_stealth, pick_user_agent, pick_viewport
from config.settings import settings
from models.tee_time import TeeTimeSlot

logger = logging.getLogger(__name__)

STATE_DIR = Path("browser_state")


class BrowserAdapter:
    """Manages a single Playwright browser session against ClubHouse Online."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._logged_in = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch the browser with stealth patches and a realistic fingerprint."""
        self._playwright = await async_playwright().start()

        # Use new headless mode which shares the same rendering pipeline
        # as headed Chrome — much harder for sites to fingerprint.
        launch_kwargs: dict = {
            "headless": settings.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        }
        # Allow overriding the Chromium binary path via environment
        if settings.chromium_path:
            launch_kwargs["executable_path"] = settings.chromium_path
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)

        # Build a realistic browser context
        user_agent = pick_user_agent()
        viewport = pick_viewport()
        logger.info("Stealth: UA=%s  viewport=%s", user_agent, viewport)

        context_kwargs: dict = {
            "user_agent": user_agent,
            "viewport": viewport,
            "locale": "en-US",
            "timezone_id": "America/Chicago",
            "color_scheme": "light",
            "java_script_enabled": True,
            "ignore_https_errors": True,
        }

        storage_path = STATE_DIR / "state.json"
        if storage_path.exists():
            logger.info("Restoring saved browser session state.")
            context_kwargs["storage_state"] = str(storage_path)

        self._context = await self._browser.new_context(**context_kwargs)

        # Inject stealth scripts that run before every page load
        if settings.stealth_enabled:
            await apply_stealth(self._context)

        self._page = await self._context.new_page()
        if settings.stealth_enabled:
            logger.info("Browser started (stealth mode).")
        else:
            logger.info("Browser started (stealth DISABLED).")

    async def stop(self) -> None:
        """Save session state and close the browser cleanly."""
        if self._context:
            STATE_DIR.mkdir(exist_ok=True)
            await self._context.storage_state(path=str(STATE_DIR / "state.json"))
            logger.info("Browser session state saved.")
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._logged_in = False
        logger.info("Browser stopped.")

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser not started — call start() first.")
        return self._page

    async def _dump_debug(self, label: str, http_status: int | None = None) -> None:
        """Save page HTML + screenshot to debug/ for inspection."""
        debug_dir = Path("debug")
        debug_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"{ts}_{label}"

        html_path = debug_dir / f"{prefix}.html"
        png_path = debug_dir / f"{prefix}.png"

        try:
            content = await self.page.content()
            html_path.write_text(content, encoding="utf-8")
            logger.info("Debug: saved page HTML to %s", html_path)
        except Exception:
            logger.debug("Debug: could not save HTML.", exc_info=True)

        try:
            await self.page.screenshot(path=str(png_path), full_page=True)
            logger.info("Debug: saved screenshot to %s", png_path)
        except Exception:
            logger.debug("Debug: could not save screenshot.", exc_info=True)

        if http_status:
            logger.info("Debug: HTTP status was %d", http_status)

    async def rotate_session(self) -> None:
        """
        Drop the current browser context and create a fresh one with a new
        fingerprint (user-agent, viewport).  Called after a block is detected
        and the cooldown expires — avoids reusing a flagged session.
        """
        logger.info("Rotating browser session (new fingerprint).")
        if self._context:
            await self._context.close()

        # Delete persisted state so the new session starts clean
        storage_path = STATE_DIR / "state.json"
        if storage_path.exists():
            storage_path.unlink()
            logger.info("Cleared saved browser state.")

        user_agent = pick_user_agent()
        viewport = pick_viewport()
        logger.info("Stealth: new UA=%s  viewport=%s", user_agent, viewport)

        self._context = await self._browser.new_context(
            user_agent=user_agent,
            viewport=viewport,
            locale="en-US",
            timezone_id="America/Chicago",
            color_scheme="light",
            java_script_enabled=True,
            ignore_https_errors=True,
        )
        if settings.stealth_enabled:
            await apply_stealth(self._context)
        self._page = await self._context.new_page()
        self._logged_in = False
        get_state().session_dirty = False

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    async def _safe_goto(self, url: str) -> None:
        """Navigate to a URL with safety delay and block detection."""
        await human_delay("navigation")
        response = await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        http_status = response.status if response else None
        if response and response.status in (403, 429, 503):
            logger.error("Safety: HTTP %d from %s — possible block.", response.status, url)

        content = await self.page.content()
        blocked = detect_block(content)

        # Dump debug info when a block is detected so we can inspect
        if blocked:
            await self._dump_debug("block_detected", http_status)

    async def _safe_click(self, selector: str) -> None:
        """Click with human-like hover → pause → click pattern."""
        await human_delay("click")
        el = await self.page.wait_for_selector(selector, timeout=10_000)
        if el:
            await el.hover()
            await asyncio.sleep(random.uniform(0.1, 0.4))
            await el.click()
        else:
            await self.page.click(selector)

    async def _safe_fill(self, selector: str, value: str) -> None:
        """Type character by character with randomized keystroke delays."""
        await human_delay("fill")
        el = await self.page.wait_for_selector(selector, timeout=10_000)
        await el.click()
        await el.fill("")  # clear first
        await el.type(value, delay=random.uniform(50, 150))

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def login(self) -> bool:
        """
        Log in to the ClubHouse Online member portal.

        Returns True on success, False on failure (safety limits enforced).
        """
        if self._logged_in:
            return True

        if not check_can_login():
            return False

        if get_state().blocked:
            logger.error("Login aborted — a security block was previously detected.")
            return False

        login_url = f"{settings.cho_base_url}/Login.aspx"
        logger.info("Navigating to login page: %s", login_url)
        await self._safe_goto(login_url)

        # Re-check after navigation — _safe_goto may have detected a block
        if get_state().blocked:
            logger.error("Login aborted — block detected on login page.")
            record_login_attempt(success=False)
            return False

        try:
            # --- Fill credentials ---
            # NOTE: These selectors must be verified against the actual portal.
            # ClubHouse Online typically uses ASP.NET WebForms with IDs like
            # #txtUserName / #txtPassword or similar.  Update as needed.
            await self._safe_fill("#txtUserName", settings.cho_username)
            await self._safe_fill("#txtPassword", settings.cho_password)
            await self._safe_click("#btnLogin")

            await self.page.wait_for_load_state("domcontentloaded", timeout=15_000)
            await human_delay("post-login")

            # Check for block or error
            content = await self.page.content()
            if detect_block(content):
                record_login_attempt(success=False)
                return False

            # A successful login typically redirects away from Login.aspx
            if "login" in self.page.url.lower():
                logger.warning("Still on login page after submit — credentials may be wrong.")
                record_login_attempt(success=False)
                return False

            self._logged_in = True
            record_login_attempt(success=True)
            return True

        except Exception:
            logger.exception("Login failed with an unexpected error.")
            record_login_attempt(success=False)
            return False

    # ------------------------------------------------------------------
    # Tee-time scraping
    # ------------------------------------------------------------------

    async def fetch_tee_times(self, target_date: datetime) -> list[TeeTimeSlot]:
        """
        Navigate to the tee sheet for *target_date* and extract available slots.

        Returns a list of TeeTimeSlot objects.

        NOTE: The selectors and page structure below are scaffolded based on
        typical ClubHouse Online / Jonas tee-sheet layouts.  You will need to
        inspect the actual DOM and adjust selectors after your first live run.
        """
        if not self._logged_in:
            logger.error("Cannot fetch tee times — not logged in.")
            return []

        if get_state().blocked:
            logger.error("Tee-time fetch aborted — security block detected.")
            return []

        date_str = target_date.strftime("%m/%d/%Y")
        tee_time_url = f"{settings.cho_base_url}/TeeTimeSearch.aspx"
        logger.info("Fetching tee times for %s", date_str)

        await self._safe_goto(tee_time_url)

        if get_state().blocked:
            logger.error("Tee-time fetch aborted — block detected after navigation.")
            return []

        try:
            # Set the date picker — adjust selector to match actual page
            date_input_selector = "#txtDate"
            await self._safe_fill(date_input_selector, date_str)
            await self._safe_click("#btnSearch")

            await self.page.wait_for_load_state("domcontentloaded", timeout=15_000)
            await human_delay("tee-sheet-load")

            content = await self.page.content()
            if detect_block(content):
                return []

            # Parse the tee-time table rows
            # Typical structure: a table/grid with rows per slot.
            # Each row contains time, available spots, course, etc.
            slots: list[TeeTimeSlot] = []

            rows = await self.page.query_selector_all(".tee-time-row, tr.teeTimeSlot")
            for row in rows:
                try:
                    time_el = await row.query_selector(".tee-time, .time-cell, td:nth-child(1)")
                    spots_el = await row.query_selector(".spots, .available-cell, td:nth-child(2)")
                    course_el = await row.query_selector(".course, .course-cell, td:nth-child(3)")

                    time_text = (await time_el.inner_text()).strip() if time_el else ""
                    spots_text = (await spots_el.inner_text()).strip() if spots_el else "0"
                    course_text = (await course_el.inner_text()).strip() if course_el else ""

                    available = int("".join(c for c in spots_text if c.isdigit()) or "0")

                    if time_text and available > 0:
                        slots.append(
                            TeeTimeSlot(
                                date=target_date,
                                time_str=time_text,
                                available_spots=available,
                                course_name=course_text,
                            )
                        )
                except Exception:
                    logger.debug("Skipping unparseable tee-time row.", exc_info=True)

            logger.info("Found %d available tee-time slots for %s.", len(slots), date_str)
            return slots

        except Exception:
            logger.exception("Error fetching tee times for %s.", date_str)
            return []

    # ------------------------------------------------------------------
    # Booking
    # ------------------------------------------------------------------

    async def book_slot(self, slot: TeeTimeSlot) -> bool:
        """
        Attempt to reserve *slot* for the configured number of players.

        Returns True on success, False on failure.

        NOTE: Booking flow selectors are scaffolded — update after inspecting
        the actual ClubHouse Online reservation confirmation flow.
        """
        if get_state().blocked:
            logger.error("Booking aborted — security block detected.")
            return False

        logger.info("Attempting to book: %s", slot)

        try:
            # Re-navigate to the tee sheet for the slot's date
            await self.fetch_tee_times(slot.date)

            # Locate and click the matching time slot
            # This selector is a best-guess — update after live inspection
            time_links = await self.page.query_selector_all("a.tee-time-link, a.bookable")
            target_found = False
            for link in time_links:
                text = (await link.inner_text()).strip()
                if slot.time_str in text:
                    await human_delay("select-slot")
                    await link.click()
                    target_found = True
                    break

            if not target_found:
                logger.warning("Could not locate the slot link for %s on the page.", slot.time_str)
                return False

            await self.page.wait_for_load_state("domcontentloaded", timeout=15_000)
            await human_delay("booking-form")

            # Set player count if a dropdown/field exists
            player_selector = "#ddlPlayers, #txtPlayers, select.player-count"
            player_el = await self.page.query_selector(player_selector)
            if player_el:
                await human_delay("player-select")
                tag = await player_el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    await player_el.select_option(str(settings.player_count))
                else:
                    await player_el.fill(str(settings.player_count))

            # Submit the reservation
            submit_selector = "#btnReserve, #btnBook, button.book-confirm"
            await self._safe_click(submit_selector)

            await self.page.wait_for_load_state("domcontentloaded", timeout=15_000)
            await human_delay("post-booking")

            content = await self.page.content()
            if detect_block(content):
                return False

            # Look for confirmation signals
            lower = content.lower()
            if any(kw in lower for kw in ["confirmed", "reservation", "booked", "success"]):
                logger.info("Booking confirmed for %s.", slot)
                return True

            logger.warning("Booking submitted but no confirmation detected — check manually.")
            return False

        except Exception:
            logger.exception("Booking failed for %s.", slot)
            return False
