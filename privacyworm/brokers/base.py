"""Base class for broker interactions."""

import logging
import os
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from string import Formatter
from typing import Callable
from urllib.parse import quote

from privacyworm.config import (
    get_network_log_path,
    get_raw_network_log_path,
    keep_raw_log_enabled,
    scrub_pii,
)
from privacyworm.playbook import SEARCH_URL_PLACEHOLDERS, Playbook
from privacyworm.profile import Profile

logger = logging.getLogger("privacyworm")


def log_network_request(method: str, url: str, details: str = "") -> None:
    """Append a line to the network audit log.

    The default log at ``network.log`` is redacted: name-shaped path
    segments and any query string are replaced before writing. Sharing
    this file with a friend should not leak your name or city.

    Setting ``PRIVACYWORM_KEEP_RAW_LOG=1`` also writes the original URL
    to ``network.raw.log`` for debugging. ``privacyworm export-audit
    --include-sensitive`` reads from there when it exists.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    safe_url = scrub_pii(url)

    log_path = get_network_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(f"{timestamp} {method} {safe_url} {details}\n")
    _owner_only(log_path)

    if keep_raw_log_enabled():
        raw_path = get_raw_network_log_path()
        with open(raw_path, "a") as f:
            f.write(f"{timestamp} {method} {url} {details}\n")
        _owner_only(raw_path)


def _owner_only(path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# Callback the guided flow passes in when a human is finishing the job.
# It receives a description of what was opened (form, email, page) and
# returns "done", "failed" or "skipped".
AssistCallback = Callable[[dict], str]

SEARCH_URL_FIELDS = SEARCH_URL_PLACEHOLDERS


def build_search_url(template: str, profile: Profile) -> str:
    """Fill a playbook ``url_template`` safely.

    Only plain ``{field}`` placeholders from ``SEARCH_URL_FIELDS`` are
    allowed - no attribute access, indexing or format specs, so a hostile
    playbook can't use ``str.format`` tricks to read program internals.
    Every value is URL-encoded, so names like "Mary Ann" or "O'Brien"
    produce a valid URL.
    """
    addr = profile.addresses[0] if profile.addresses else None
    values = {
        "first": profile.name.first.strip(),
        "last": profile.name.last.strip(),
        "middle": (profile.name.middle or "").strip(),
        "city": addr.city.strip() if addr else "",
        "state": addr.state.strip().upper() if addr else "",
        "zip": addr.zip.strip() if addr else "",
    }
    out = []
    for literal, field, spec, conv in Formatter().parse(template):
        out.append(literal)
        if field is None:
            continue
        if field not in SEARCH_URL_FIELDS or spec or conv:
            raise ValueError(f"Unsupported placeholder {{{field}}} in url_template")
        out.append(quote(values[field], safe=""))
    return "".join(out)


class BaseBroker(ABC):
    def __init__(self, playbook: Playbook, profile: Profile, headed: bool = False):
        self.playbook = playbook
        self.profile = profile
        self.headed = headed
        # Set by scan(): "ok", "blocked" or "error", plus a human note.
        self.scan_status = "ok"
        self.scan_note = ""

    def scan(self) -> list[dict]:
        """Search the broker for listings matching the profile.

        Returns a list of dicts, each with ``listing_url``,
        ``matched_name`` and ``raw_snippet``. After the call,
        ``scan_status`` says whether the result can be trusted: a CAPTCHA
        wall or a crash is reported as "blocked"/"error", never as "clean".
        """
        from privacyworm.browser import detect_block, open_browser

        url = self._build_search_url()
        log_network_request("GET", url, "scan")
        logger.debug(f"Scanning {self.playbook.display_name}")

        results: list[dict] = []
        self.scan_status, self.scan_note = "ok", ""
        with open_browser(headless=not self.headed) as (_browser, page):
            response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:  # noqa: BLE001 - busy pages never go idle; that's fine
                pass

            block = detect_block(page, response)
            if block and self.headed and sys.stdin.isatty():
                print(
                    f"\n  {self.playbook.display_name} wants to check you're human ({block}).\n"
                    "  Solve it in the browser window, then press Enter here."
                )
                try:
                    input("  Press Enter when the results are showing... ")
                except EOFError:
                    pass
                block = detect_block(page)
            if block:
                self.scan_status, self.scan_note = "blocked", block
                return []

            for selector in self.playbook.search.listing_selectors:
                for el in page.query_selector_all(selector):
                    text = el.inner_text()
                    link_el = el.query_selector("a")
                    link = link_el.get_attribute("href") if link_el else None
                    if link and not link.startswith("http"):
                        link = self.playbook.homepage.rstrip("/") + "/" + link.lstrip("/")
                    results.append({
                        # Fall back to the search page so the user always
                        # has something to open, and so repeated scans
                        # don't pile up duplicate NULL-URL rows.
                        "listing_url": link or url,
                        "matched_name": text.split("\n")[0].strip() if text else None,
                        "matched_city": None,
                        "matched_state": None,
                        "raw_snippet": text[:500] if text else None,
                    })

            if not results:
                # Zero cards matched. If the page still mentions the user's
                # name, the site's layout probably changed and our
                # selectors are stale - say so instead of reporting "clean".
                try:
                    body = (page.inner_text("body", timeout=2_000) or "").lower()
                except Exception:  # noqa: BLE001
                    body = ""
                first = self.profile.name.first.lower()
                last = self.profile.name.last.lower()
                if first and last and first in body and last in body:
                    self.scan_status = "unreadable"
                    self.scan_note = "the site's layout changed, so results couldn't be read"

        return self._filter_matches(results)

    def _filter_matches(self, results: list[dict]) -> list[dict]:
        """Keep only results whose name line mentions the user (or an alias)."""
        first = self.profile.name.first.lower()
        last = self.profile.name.last.lower()
        aliases = [a.lower().split() for a in self.profile.aliases if a.strip()]
        matched = []
        for r in results:
            name = (r.get("matched_name") or "").lower()
            if first in name and last in name:
                matched.append(r)
            elif any(parts and all(part in name for part in parts) for parts in aliases):
                matched.append(r)
        return matched

    @abstractmethod
    def file_optout(
        self,
        listing: dict,
        dry_run: bool = False,
        assist: AssistCallback | None = None,
    ) -> dict:
        """File an opt-out request for a specific listing.

        With ``assist`` set, a visible browser / mail draft is prepared
        and the human finishes the last step (CAPTCHA, Submit, Send).

        Returns a dict with:
            - success: bool
            - method: str
            - details: str
        """
        ...

    def _build_search_url(self) -> str:
        """Fill in the search URL template with profile fields."""
        return build_search_url(self.playbook.search.url_template, self.profile)
