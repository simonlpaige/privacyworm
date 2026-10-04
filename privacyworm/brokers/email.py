"""Email-based broker opt-outs via SMTP.

For email-based opt-outs, we use the user's first configured email as
the sender/reply-to. The SMTP server details come from environment
variables PRIVACYWORM_SMTP_HOST, PRIVACYWORM_SMTP_PORT,
PRIVACYWORM_SMTP_USER, PRIVACYWORM_SMTP_PASS. If they aren't set,
dry-run still works; live sends will fail loudly.
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText
from string import Template
from urllib.parse import quote

from privacyworm.brokers.base import AssistCallback, BaseBroker, log_network_request
from privacyworm.playbook import Playbook, resolve_legal_basis
from privacyworm.profile import Profile

logger = logging.getLogger("privacyworm")

SMTP_HOST = os.environ.get("PRIVACYWORM_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("PRIVACYWORM_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("PRIVACYWORM_SMTP_USER", "")
SMTP_PASS = os.environ.get("PRIVACYWORM_SMTP_PASS", "")


def smtp_configured() -> bool:
    """True when the user set SMTP credentials for direct sending."""
    return bool(SMTP_USER and SMTP_PASS)


def build_mailto(to_addr: str, subject: str, body: str) -> str:
    """A mailto: link that opens a filled-in draft in the default mail app."""
    body = body.replace("\r\n", "\n").replace("\n", "\r\n")
    return f"mailto:{quote(to_addr, safe='@')}?subject={quote(subject)}&body={quote(body)}"


class EmailBroker(BaseBroker):
    def __init__(self, playbook: Playbook, profile: Profile, headed: bool = False):
        super().__init__(playbook, profile, headed)

    def file_optout(
        self,
        listing: dict,
        dry_run: bool = False,
        assist: AssistCallback | None = None,
    ) -> dict:
        """Send an opt-out email to the broker.

        With SMTP settings in the environment, the email is sent directly.
        Without them (the normal case), assisted mode opens a ready-to-send
        draft in the user's own mail app - no passwords to configure.
        """
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

        if assist is not None and not smtp_configured():
            mailto = build_mailto(to_addr, subject, body)
            log_network_request("MAILTO", f"mailto:{to_addr}", "opt-out email draft opened")
            outcome = assist({
                "kind": "email",
                "broker": self.playbook.display_name,
                "to": to_addr,
                "subject": subject,
                "body": body,
                "mailto": mailto,
                "requires_confirmation": opt.requires_confirmation,
            })
            if outcome == "done":
                return {"success": True, "method": "email", "details": f"Sent from your mail app to {to_addr}"}
            if outcome == "skipped":
                return {"success": False, "method": "skipped", "details": "Skipped for now."}
            return {"success": False, "method": "email", "details": "You reported the email wasn't sent."}

        if not smtp_configured():
            return {
                "success": False,
                "method": "email",
                "details": (
                    f"No mail server set up. Run 'privacyworm' (guided mode) to send this "
                    f"from your own mail app, or email {to_addr} yourself."
                ),
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

    def _build_email_body(self, listing: dict) -> str:
        state_code = (
            self.profile.addresses[0].state if self.profile.addresses else None
        )
        legal_basis = resolve_legal_basis(self.playbook, state_code) or (
            "Voluntary deletion request"
        )

        opt = self.playbook.opt_out
        if opt.email_body_template:
            return Template(opt.email_body_template).safe_substitute(
                first=self.profile.name.first,
                last=self.profile.name.last,
                email=self.profile.emails[0] if self.profile.emails else "",
                listing_url=listing.get("listing_url", ""),
                full_name=f"{self.profile.name.first} {self.profile.name.last}",
                legal_basis=legal_basis,
            )

        listing_url = listing.get("listing_url", "N/A")
        return (
            f"To whom it may concern,\n\n"
            f"I am writing to request the removal of my personal information "
            f"from your website. This request is made under: {legal_basis}.\n\n"
            f"Name: {self.profile.name.first} {self.profile.name.last}\n"
            f"Listing URL: {listing_url}\n"
            f"Email: {self.profile.emails[0] if self.profile.emails else 'N/A'}\n\n"
            f"Please remove this listing and confirm the removal in writing.\n\n"
            f"Thank you."
        )
