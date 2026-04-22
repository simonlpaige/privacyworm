"""Playwright-driven broker for web form opt-outs."""

import logging

from privacyworm.brokers.base import BaseBroker, log_network_request
from privacyworm.playbook import Playbook
from privacyworm.profile import Profile

logger = logging.getLogger("privacyworm")


class WebFormBroker(BaseBroker):
    def __init__(self, playbook: Playbook, profile: Profile, headed: bool = False):
        super().__init__(playbook, profile, headed)

    def scan(self) -> list[dict]:
        """Use Playwright to search the broker and extract matching listings."""
        from playwright.sync_api import sync_playwright

        url = self._build_search_url()
        log_network_request("GET", url, "scan")
        logger.info(f"Scanning {self.playbook.display_name}: {url}")

        results = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not self.headed)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            for selector in self.playbook.search.listing_selectors:
                elements = page.query_selector_all(selector)
                for el in elements:
                    text = el.inner_text()
                    link_el = el.query_selector("a")
                    link = link_el.get_attribute("href") if link_el else None
                    if link and not link.startswith("http"):
                        link = self.playbook.homepage.rstrip("/") + link

                    results.append({
                        "listing_url": link,
                        "matched_name": text.split("\n")[0].strip() if text else None,
                        "matched_city": None,
                        "matched_state": None,
                        "raw_snippet": text[:500] if text else None,
                    })

            browser.close()

        return self._filter_matches(results)

    def file_optout(self, listing: dict, dry_run: bool = False) -> dict:
        """Fill and submit the broker's opt-out web form."""
        opt = self.playbook.opt_out
        if not opt.url or not opt.form:
            return {"success": False, "method": "web_form", "details": "No opt-out URL or form config in playbook"}

        if dry_run:
            payload = self._build_dry_run_payload(listing)
            return {"success": True, "method": "web_form", "details": f"DRY RUN - would submit to {opt.url}: {payload}"}

        from playwright.sync_api import sync_playwright

        log_network_request("POST", opt.url, "opt-out form submission")
        logger.info(f"Filing opt-out with {self.playbook.display_name}: {opt.url}")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not self.headed)
            page = browser.new_page()
            page.goto(opt.url, wait_until="domcontentloaded", timeout=30_000)

            form = opt.form
            if form.email_field and self.profile.emails:
                page.fill(form.email_field, self.profile.emails[0])
            if form.url_field and listing.get("listing_url"):
                page.fill(form.url_field, listing["listing_url"])
            if form.name_field:
                full_name = f"{self.profile.name.first} {self.profile.name.last}"
                page.fill(form.name_field, full_name)

            for selector, value in (form.extra_fields or {}).items():
                filled_value = value.format(
                    first=self.profile.name.first,
                    last=self.profile.name.last,
                    email=self.profile.emails[0] if self.profile.emails else "",
                )
                page.fill(selector, filled_value)

            if form.submit_button:
                page.click(form.submit_button)
                page.wait_for_timeout(2000)

            browser.close()

        return {"success": True, "method": "web_form", "details": f"Submitted opt-out form at {opt.url}"}

    def _filter_matches(self, results: list[dict]) -> list[dict]:
        """Keep only results that look like they match the user's profile."""
        matched = []
        name_variants = {self.profile.name.first.lower(), self.profile.name.last.lower()}
        for alias in self.profile.aliases:
            for part in alias.lower().split():
                name_variants.add(part)

        for r in results:
            name = (r.get("matched_name") or "").lower()
            if self.profile.name.first.lower() in name and self.profile.name.last.lower() in name:
                matched.append(r)

        return matched

    def _build_dry_run_payload(self, listing: dict) -> dict:
        """Build the payload that would be submitted, for dry-run display."""
        form = self.playbook.opt_out.form
        payload = {}
        if form:
            if form.email_field and self.profile.emails:
                payload["email"] = self.profile.emails[0]
            if form.url_field and listing.get("listing_url"):
                payload["listing_url"] = listing["listing_url"]
            if form.name_field:
                payload["name"] = f"{self.profile.name.first} {self.profile.name.last}"
        return payload
