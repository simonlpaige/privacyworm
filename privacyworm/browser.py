"""One place that knows how to open a browser.

Everything that drives a web page (scans, opt-out forms, confirmation
links) goes through ``open_browser``. That gives us three things the
old copy-pasted ``p.chromium.launch(...)`` calls did not:

1. **No 150 MB download for most people.** We try the Google Chrome or
   Microsoft Edge that is already installed first. Playwright's bundled
   Chromium is only fetched when neither exists (common on Linux).
2. **A friendly fix when nothing works**, instead of a Playwright stack
   trace telling the user to run a command they have never heard of.
3. **Block-page detection**, so a CAPTCHA wall shows up as "couldn't
   check" instead of a false "clean".

Overrides, for people who want them:
  PRIVACYWORM_BROWSER=chrome|msedge|chromium   force one browser
  PRIVACYWORM_BROWSER_PATH=/path/to/browser    use any Chromium-based binary
"""

from __future__ import annotations

import logging
import os
import subprocess  # nosec B404 - only used to run Playwright's own installer
import sys
import webbrowser
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("privacyworm")

CHANNEL_ORDER = ("chrome", "msedge", "chromium")

# Words that show up on bot walls and challenge pages. Checked against the
# page title and the first chunk of visible text.
_BLOCK_MARKERS = (
    "just a moment",
    "attention required",
    "verify you are human",
    "verify you're human",
    "are you a robot",
    "are you human",
    "captcha",
    "access denied",
    "unusual traffic",
    "press & hold",
    "press and hold",
    "checking your browser",
    "request blocked",
)
_BLOCK_FRAME_HINTS = ("recaptcha", "hcaptcha", "challenges.cloudflare.com", "turnstile", "px-captcha")

_working_channel: str | None = None


class BrowserUnavailable(RuntimeError):
    """Raised when no usable browser could be started."""


def _launch_one(p: Any, channel: str, headless: bool):
    path = os.environ.get("PRIVACYWORM_BROWSER_PATH", "").strip()
    if path:
        return p.chromium.launch(executable_path=path, headless=headless)
    if channel == "chromium":
        return p.chromium.launch(headless=headless)
    return p.chromium.launch(channel=channel, headless=headless)


def _channels_to_try() -> list[str]:
    forced = os.environ.get("PRIVACYWORM_BROWSER", "").strip().lower()
    if forced:
        return [forced]
    if _working_channel:
        return [_working_channel]
    return list(CHANNEL_ORDER)


def launch(p: Any, headless: bool = True):
    """Start the first browser that works and remember which one it was."""
    global _working_channel
    errors = []
    for channel in _channels_to_try():
        try:
            browser = _launch_one(p, channel, headless)
            _working_channel = channel
            return browser
        except Exception as e:  # noqa: BLE001 - we report all of them below
            errors.append(f"{channel}: {str(e).splitlines()[0] if str(e) else e!r}")
    raise BrowserUnavailable(
        "Couldn't start a web browser. Run 'privacyworm doctor' to fix this.\n  "
        + "\n  ".join(errors)
    )


def new_page(browser: Any):
    """Open a page that doesn't announce itself as 'HeadlessChrome'.

    Headless Chrome puts 'HeadlessChrome' in its user agent, which is the
    first thing bot walls look for. We keep the real browser version and
    just drop the word 'Headless', so the request looks like the same
    browser the user would be using anyway.
    """
    ua = None
    try:
        probe = browser.new_page()
        ua = probe.evaluate("navigator.userAgent")
        probe.close()
    except Exception:  # noqa: BLE001
        ua = None
    if ua and "HeadlessChrome" in ua:
        context = browser.new_context(user_agent=ua.replace("HeadlessChrome", "Chrome"))
    else:
        context = browser.new_context()
    return context.new_page()


@contextmanager
def open_browser(headless: bool = True) -> Iterator[tuple[Any, Any]]:
    """Context manager yielding ``(browser, page)``; always cleans up."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = launch(p, headless=headless)
        try:
            yield browser, new_page(browser)
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001 - the user may have closed the window
                pass


def detect_block(page: Any, response: Any = None) -> str | None:
    """Return a short reason when the page looks like a bot wall, else None."""
    try:
        if response is not None and response.status in (403, 429, 503):
            return f"the site answered with HTTP {response.status}"
    except Exception:  # noqa: BLE001
        pass
    try:
        title = (page.title() or "").lower()
    except Exception:  # noqa: BLE001
        title = ""
    try:
        text = (page.inner_text("body", timeout=2_000) or "")[:3000].lower()
    except Exception:  # noqa: BLE001
        text = ""
    for marker in _BLOCK_MARKERS:
        if marker in title or marker in text:
            return f"the page shows a '{marker}' check"
    try:
        for frame in page.frames:
            url = (frame.url or "").lower()
            if any(h in url for h in _BLOCK_FRAME_HINTS):
                return "the page shows a CAPTCHA"
    except Exception:  # noqa: BLE001
        pass
    return None


def open_in_default_browser(url: str) -> bool:
    """Open a URL (or mailto: link) in the user's normal browser / mail app."""
    try:
        return bool(webbrowser.open(url, new=2))
    except Exception:  # noqa: BLE001
        return False


# -- Setup / doctor -------------------------------------------------------


def check_browser() -> tuple[bool, str]:
    """Try to start a headless browser. Returns (ok, description)."""
    global _working_channel
    _working_channel = None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "Playwright isn't installed (reinstall PrivacyWorm)."
    try:
        with sync_playwright() as p:
            b = launch(p, headless=True)
            version = b.version
            b.close()
    except BrowserUnavailable as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    names = {"chrome": "Google Chrome", "msedge": "Microsoft Edge", "chromium": "built-in Chromium"}
    label = names.get(_working_channel or "", _working_channel or "custom browser")
    return True, f"{label} {version}"


def install_bundled_chromium() -> bool:
    """Download Playwright's Chromium. Shows Playwright's own progress bar."""
    cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    try:
        return subprocess.call(cmd) == 0  # nosec B603 - fixed argv, no shell
    except OSError:
        return False


def ensure_browser(echo=print) -> bool:
    """Make sure some browser works, downloading Chromium only if needed."""
    ok, desc = check_browser()
    if ok:
        echo(f"Browser: {desc}")
        return True
    echo("No Chrome or Edge found. Downloading a private copy of Chromium (one time, ~150 MB)...")
    if not install_bundled_chromium():
        echo("The download didn't finish. Check your internet connection and try 'privacyworm doctor'.")
        return False
    ok, desc = check_browser()
    if ok:
        echo(f"Browser: {desc}")
        return True
    echo("Chromium downloaded but won't start:")
    echo(f"  {desc}")
    if sys.platform.startswith("linux"):
        echo(
            "On Linux this usually means some system libraries are missing. Fix it with:\n"
            f"  sudo {sys.executable} -m playwright install-deps chromium"
        )
    return False
