"""Email-based broker opt-outs via SMTP."""

import logging
import smtplib
from email.mime.text import MIMEText

from privacyworm.brokers.base import BaseBroker, log_network_request
from privacyworm.playbook import Playbook
from privacyworm.profile import Profile

logger = logging.getLogger("privacyworm")

# Assumption: for email-based opt-outs, we use the user's first configured email
# as the sender/reply-to. The SMTP server details come from environment variables
# PRIVACYWORM_SMTP_HOST, PRIVACYWORM_SMTP_PORT, PRIVACYWORM_SMTP_USER,
# PRIVACYWORM_SMTP_PASS. If not set, dry-run still works but live sends will fail.

import os

SMTP_HOST = os.environ.get("PRIVACYWORM_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("PRIVACYWORM_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("PRIVACYWORM_SMTP_USER", "")
SMTP_PASS = os.environ.get("PRIVACYWORM_SMTP_PASS", "")


class EmailBroker(BaseBroker):
    def __init__(self, playbook: Playbook, profile: Profile, headed: bool = False):
        super().__init__(playbook, profile, headed)

    def scan(self) -> list[dict]:
        """Use Playwright to search the broker site, same as web form."""
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
        """Send an opt-out email to the broker."""
        opt = self.playbook.opt_out
        if not opt.email_address:
            return {"success": False, "method": "email", "details": "No email_address in playbook"}

        subject = opt.email_subject or f"Data Removal Request - {self.profile.name.first} {self.profile.name.last}"
        body = self._build_email_body(listing)
        to_addr = opt.email_address
        from_addr = self.profile.emails[0] if self.profile.emails else SMTP_USER

        if dry_run:
            return {
                "success": True,
                "method": "email",
                "details": f"DRY RUN - would send email to {to_addr}\n"
                           f"  From: {from_addr}\n"
                           f"  Subject: {subject}\n"
                           f"  Body:\n{body}",
            }

        log_network_request("SMTP", f"{SMTP_HOST}:{SMTP_PORT} -> {to_addr}", "opt-out email")
        logger.info(f"Sending opt-out email to {to_addr} for {self.playbook.display_name}")

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr

        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                if SMTP_USER and SMTP_PASS:
                    server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
            return {"success": True, "method": "email", "details": f"Sent opt-out email to {to_addr}"}
        except Exception as e:
            return {"success": False, "method": "email", "details": f"SMTP error: {e}"}

    def _filter_matches(self, results: list[dict]) -> list[dict]:
        matched = []
        for r in results:
            name = (r.get("matched_name") or "").lower()
            if self.profile.name.first.lower() in name and self.profile.name.last.lower() in name:
                matched.append(r)
        return matched

    def _build_email_body(self, listing: dict) -> str:
        opt = self.playbook.opt_out
        if opt.email_body_template:
            return opt.email_body_template.format(
                first=self.profile.name.first,
                last=self.profile.name.last,
                email=self.profile.emails[0] if self.profile.emails else "",
                listing_url=listing.get("listing_url", ""),
                full_name=f"{self.profile.name.first} {self.profile.name.last}",
            )

        listing_url = listing.get("listing_url", "N/A")
        return (
            f"To whom it may concern,\n\n"
            f"I am writing to request the removal of my personal information "
            f"from your website.\n\n"
            f"Name: {self.profile.name.first} {self.profile.name.last}\n"
            f"Listing URL: {listing_url}\n"
            f"Email: {self.profile.emails[0] if self.profile.emails else 'N/A'}\n\n"
            f"Please remove this listing and confirm the removal.\n\n"
            f"Thank you."
        )
