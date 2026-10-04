"""Playwright-driven broker for web form opt-outs."""

import logging
from string import Template

from privacyworm.brokers.base import AssistCallback, BaseBroker, log_network_request
from privacyworm.playbook import Playbook
from privacyworm.profile import Profile

logger = logging.getLogger("privacyworm")

# How long to look for a form field before giving up on it. In assisted
# mode the human can fill anything we miss, so there's no point waiting
# the default 30 seconds per selector.
FIELD_TIMEOUT_MS = 4_000


class WebFormBroker(BaseBroker):
    def __init__(self, playbook: Playbook, profile: Profile, headed: bool = False):
        super().__init__(playbook, profile, headed)

    def _form_values(self, listing: dict) -> list[tuple[str, str, str]]:
        """(label, selector, value) for every field the playbook wants filled."""
        form = self.playbook.opt_out.form
        if not form:
            return []
        out: list[tuple[str, str, str]] = []
        if form.email_field and self.profile.emails:
            out.append(("Email", form.email_field, self.profile.emails[0]))
        if form.url_field and listing.get("listing_url"):
            out.append(("Listing URL", form.url_field, listing["listing_url"]))
        if form.name_field:
            out.append(("Name", form.name_field, f"{self.profile.name.first} {self.profile.name.last}"))
        for selector, value in (form.extra_fields or {}).items():
            filled_value = Template(value).safe_substitute(
                first=self.profile.name.first,
                last=self.profile.name.last,
                email=self.profile.emails[0] if self.profile.emails else "",
                state=self.profile.addresses[0].state if self.profile.addresses else "",
                city=self.profile.addresses[0].city if self.profile.addresses else "",
            )
            out.append((selector, selector, filled_value))
        return out

    def file_optout(
        self,
        listing: dict,
        dry_run: bool = False,
        assist: AssistCallback | None = None,
    ) -> dict:
        """Fill and submit the broker's opt-out web form.

        Automatic mode fills the form and clicks Submit. Assisted mode
        (``assist`` given) opens a visible window, pre-fills what it can,
        and lets the person solve any CAPTCHA and press Submit themselves -
        which is what most real broker forms need anyway.
        """
        from privacyworm.browser import open_browser

        opt = self.playbook.opt_out
        if not opt.url or not opt.form:
            return {"success": False, "method": "web_form", "details": "No opt-out URL or form config in playbook"}

        if dry_run:
            payload = self._build_dry_run_payload(listing)
            return {"success": True, "method": "web_form", "details": f"DRY RUN - would submit to {opt.url}: {payload}"}

        log_network_request("POST", opt.url, "opt-out form submission")
        logger.debug(f"Filing opt-out with {self.playbook.display_name}")
        values = self._form_values(listing)

        if assist is not None:
            # A person is finishing this one, so use their own browser: an
            # automated window gets flagged by Cloudflare-style checks and
            # the "I'm not a robot" box can loop forever.
            from privacyworm.browser import open_in_default_browser

            open_in_default_browser(opt.url)
            outcome = assist({
                "kind": "web_form",
                "broker": self.playbook.display_name,
                "url": opt.url,
                "fields": {label: value for label, _sel, value in values},
                "missed": {},
                "requires_confirmation": opt.requires_confirmation,
            })
            return _outcome_result("web_form", outcome, opt.url)

        try:
            with open_browser(headless=(assist is None and not self.headed)) as (_browser, page):
                page.goto(opt.url, wait_until="domcontentloaded", timeout=30_000)

                missed: list[tuple[str, str]] = []
                for label, selector, value in values:
                    try:
                        page.fill(selector, value, timeout=FIELD_TIMEOUT_MS)
                    except Exception:  # noqa: BLE001
                        if assist is None:
                            raise
                        missed.append((label, value))

                if assist is not None:
                    outcome = assist({
                        "kind": "web_form",
                        "broker": self.playbook.display_name,
                        "url": opt.url,
                        "fields": {label: value for label, _sel, value in values},
                        "missed": dict(missed),
                        "requires_confirmation": opt.requires_confirmation,
                    })
                    return _outcome_result("web_form", outcome, opt.url)

                if opt.form.submit_button:
                    page.click(opt.form.submit_button, timeout=10_000)
                    page.wait_for_timeout(2000)
        except Exception as e:  # noqa: BLE001
            return {"success": False, "method": "web_form", "details": f"Couldn't complete the form: {_short(e)}"}

        return {"success": True, "method": "web_form", "details": f"Submitted opt-out form at {opt.url}"}

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


def _short(e: Exception) -> str:
    text = str(e).strip().splitlines()
    return text[0] if text else type(e).__name__


def _outcome_result(method: str, outcome: str, where: str) -> dict:
    if outcome == "done":
        return {"success": True, "method": method, "details": f"Submitted (you confirmed) at {where}"}
    if outcome == "skipped":
        return {"success": False, "method": "skipped", "details": "Skipped for now."}
    return {"success": False, "method": method, "details": "You reported it didn't go through."}
