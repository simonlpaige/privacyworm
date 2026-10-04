"""Send and read mail from the user's own mailbox.

Requests go out from *your* address, so replies, confirmation links and
"we've deleted your data" notes land in *your* inbox, where the triage
step reads them. Works with any provider that offers IMAP/SMTP with an
app password (Gmail, Yahoo, iCloud, Fastmail, most others).
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import os
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Callable

from privacyworm.brokers.base import log_network_request
from privacyworm.profile import InboxConfig

# domain -> (imap host, smtp host, smtp port, where to make an app password)
PROVIDERS = {
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com", 587, "https://myaccount.google.com/apppasswords"),
    "googlemail.com": ("imap.gmail.com", "smtp.gmail.com", 587, "https://myaccount.google.com/apppasswords"),
    "yahoo.com": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com", 465, "https://login.yahoo.com/account/security/app-passwords"),
    "icloud.com": ("imap.mail.me.com", "smtp.mail.me.com", 587, "https://account.apple.com/account/manage"),
    "me.com": ("imap.mail.me.com", "smtp.mail.me.com", 587, "https://account.apple.com/account/manage"),
    "fastmail.com": ("imap.fastmail.com", "smtp.fastmail.com", 465, "https://app.fastmail.com/settings/security/apps"),
    "outlook.com": ("outlook.office365.com", "smtp-mail.outlook.com", 587, "https://account.live.com/proofs/AppPassword"),
    "hotmail.com": ("outlook.office365.com", "smtp-mail.outlook.com", 587, "https://account.live.com/proofs/AppPassword"),
    "live.com": ("outlook.office365.com", "smtp-mail.outlook.com", 587, "https://account.live.com/proofs/AppPassword"),
    "aol.com": ("imap.aol.com", "smtp.aol.com", 465, "https://login.aol.com/account/security"),
}


def provider_for(address: str) -> tuple[str, str, int, str | None]:
    domain = address.rsplit("@", 1)[-1].lower()
    if domain in PROVIDERS:
        return PROVIDERS[domain]
    return (f"imap.{domain}", f"smtp.{domain}", 587, None)


def _password(cfg: InboxConfig) -> str:
    return os.environ.get(cfg.pass_env, "") or (cfg.password or "")


def _smtp_target(cfg: InboxConfig) -> tuple[str, int]:
    _imap, smtp_host, smtp_port, _ = provider_for(cfg.user)
    return cfg.smtp_host or smtp_host, cfg.smtp_port or smtp_port


class Mailbox:
    """A connected pair of SMTP (send) and IMAP (read) for one account."""

    def __init__(self, cfg: InboxConfig, display_name: str = ""):
        self.cfg = cfg
        self.display_name = display_name
        self._smtp: smtplib.SMTP | None = None

    # -- sending ------------------------------------------------------------

    def _connect_smtp(self) -> smtplib.SMTP:
        host, port = _smtp_target(self.cfg)
        ctx = ssl.create_default_context()
        server: smtplib.SMTP
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.starttls(context=ctx)
        server.login(self.cfg.user, _password(self.cfg))
        return server

    def send(
        self,
        to_addr: str,
        subject: str,
        body: str,
        in_reply_to: list[str] | None = None,
    ) -> str:
        """Send one plain-text email. Returns its Message-ID."""
        domain = self.cfg.user.rsplit("@", 1)[-1]
        msg = EmailMessage()
        msg["From"] = formataddr((self.display_name, self.cfg.user)) if self.display_name else self.cfg.user
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg_id = make_msgid(domain=domain)
        msg["Message-ID"] = msg_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to[-1]
            msg["References"] = " ".join(in_reply_to)
        msg.set_content(body)
        log_network_request("SMTP", f"smtp -> {to_addr.split('@')[-1]}", "deletion request")
        if self._smtp is None:
            self._smtp = self._connect_smtp()
        try:
            self._smtp.send_message(msg)
        except smtplib.SMTPServerDisconnected:
            self._smtp = self._connect_smtp()
            self._smtp.send_message(msg)
        return msg_id

    def close(self) -> None:
        if self._smtp is not None:
            try:
                self._smtp.quit()
            except Exception:  # noqa: BLE001
                pass
            self._smtp = None

    # -- reading ------------------------------------------------------------

    def fetch_since(
        self,
        since: datetime,
        want: Callable[[email.message.EmailMessage], bool] | None = None,
    ) -> list[email.message.EmailMessage]:
        """Inbox messages since a date that ``want(headers)`` accepts.

        Only headers are downloaded for everything; full bodies only for
        messages ``want`` picks, so a busy inbox stays quick. Messages are
        fetched with PEEK - nothing is marked read.
        """
        conn = imaplib.IMAP4_SSL(self.cfg.host, self.cfg.port, timeout=60)
        log_network_request("IMAP", f"{self.cfg.host}:{self.cfg.port}", "read replies")
        try:
            conn.login(self.cfg.user, _password(self.cfg))
            conn.select("INBOX", readonly=True)
            day = (since - timedelta(days=1)).strftime("%d-%b-%Y")
            _, data = conn.search(None, f"(SINCE {day})")
            nums = (data[0] or b"").split()
            picked: list[bytes] = []
            for i in range(0, len(nums), 200):
                chunk = b",".join(nums[i:i + 200]).decode()
                _, resp = conn.fetch(
                    chunk,
                    "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT MESSAGE-ID IN-REPLY-TO REFERENCES)])",
                )
                for part in resp:
                    if not isinstance(part, tuple):
                        continue
                    num = part[0].split()[0]
                    head = email.message_from_bytes(part[1], policy=email.policy.default)
                    if want is None or want(head):  # type: ignore[arg-type]
                        picked.append(num)
            out: list[email.message.EmailMessage] = []
            for num in picked:
                _, resp = conn.fetch(num.decode(), "(BODY.PEEK[])")
                for part in resp:
                    if isinstance(part, tuple):
                        out.append(email.message_from_bytes(part[1], policy=email.policy.default))  # type: ignore[arg-type]
            return out
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass

    # -- setup check ----------------------------------------------------------

    def test(self) -> tuple[bool, str]:
        """Log in to both servers. Returns (ok, human message)."""
        try:
            s = self._connect_smtp()
            s.quit()
        except smtplib.SMTPAuthenticationError:
            return False, "The mail server rejected the app password. Make a new one and try again."
        except Exception as e:  # noqa: BLE001
            return False, f"Couldn't reach the outgoing mail server ({e})."
        try:
            conn = imaplib.IMAP4_SSL(self.cfg.host, self.cfg.port, timeout=30)
            conn.login(self.cfg.user, _password(self.cfg))
            conn.logout()
        except imaplib.IMAP4.error:
            return False, "Sending works, but reading the inbox was refused. Is IMAP turned on for this account?"
        except Exception as e:  # noqa: BLE001
            return False, f"Couldn't reach the incoming mail server ({e})."
        return True, "Connected. PrivacyWorm can send requests and read replies."
