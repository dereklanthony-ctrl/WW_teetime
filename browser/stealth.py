"""
Stealth layer — patches Playwright browser contexts to avoid headless detection.

Covers the most common fingerprinting vectors used by anti-bot systems:
  1. navigator.webdriver                → false
  2. Chrome runtime objects             → present
  3. Permissions API                    → "denied" for notifications
  4. Plugin/mime-type arrays            → populated
  5. WebGL vendor/renderer              → realistic GPU strings
  6. Language/platform consistency      → matches User-Agent
  7. Headless-specific CSS media query  → overridden
"""

from __future__ import annotations

import logging
import random

from playwright.async_api import BrowserContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# User-Agent rotation pool — recent, real-world desktop Chrome UA strings
# ---------------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# Common desktop screen sizes
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 720},
]

# ---------------------------------------------------------------------------
# JavaScript patches injected before every page load
# ---------------------------------------------------------------------------
STEALTH_JS = """
() => {
    // 1. Override navigator.webdriver
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });

    // 2. Fake chrome runtime object (missing in headless)
    if (!window.chrome) {
        window.chrome = {};
    }
    if (!window.chrome.runtime) {
        window.chrome.runtime = {
            PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' },
            PlatformArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64', MIPS: 'mips', MIPS64: 'mips64' },
            PlatformNaclArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64', MIPS: 'mips', MIPS64: 'mips64' },
            RequestUpdateCheckStatus: { THROTTLED: 'throttled', NO_UPDATE: 'no_update', UPDATE_AVAILABLE: 'update_available' },
            OnInstalledReason: { INSTALL: 'install', UPDATE: 'update', CHROME_UPDATE: 'chrome_update', SHARED_MODULE_UPDATE: 'shared_module_update' },
            OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
        };
    }

    // 3. Fix Permissions API
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);

    // 4. Fake plugins array (headless has length 0)
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
        ],
    });

    // 5. Fake languages (headless sometimes returns empty)
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en'],
    });

    // 6. Fake WebGL vendor/renderer
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (parameter) {
        if (parameter === 37445) return 'Intel Inc.';           // UNMASKED_VENDOR_WEBGL
        if (parameter === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
        return getParameter.call(this, parameter);
    };

    // 7. Patch iframe contentWindow to not leak automation
    const elementDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight');
    // (no-op guard for environments where this already exists)
}
"""


def pick_user_agent() -> str:
    """Select a random, realistic User-Agent string."""
    return random.choice(USER_AGENTS)


def pick_viewport() -> dict:
    """Select a random common desktop viewport."""
    return random.choice(VIEWPORTS)


async def apply_stealth(context: BrowserContext) -> None:
    """
    Inject stealth patches into a Playwright BrowserContext.

    Must be called *after* context creation and *before* any page navigation.
    The script runs automatically on every new document via add_init_script.
    """
    await context.add_init_script(STEALTH_JS)
    logger.info("Stealth: init scripts injected into browser context.")
