"""IMAP inbox watcher for broker confirmation emails."""

import email
import imaplib
import logging
import os
import re

from privacyworm.brokers.base import log_network_request
from privacyworm.inbox.base import BaseInbox
from privacyworm.profile import InboxConfig

logger = logging.getLogger("privacyworm")

URL_PATTERN = re.compile(r'https?://[^\s<>"\']+')


class ImapInbox(BaseInbox):
    def __init__(self, config: InboxConfig):
        self.host = config.host
        self.port = config.port
        self.user = config.user
        self.password = os.environ.get(config.pass_env, "")

    def check_confirmations(self, subject_contains: str) -> list[dict]:
        """Search IMAP INBOX for unread messages matching the subject.

        Each result dict carries:
            subject, from_addr, body, links, uid, body_source

        ``body_source`` is "text" when the URLs were extracted from a
        text/plain part and "html" when only an HTML part was present.
        Callers should treat HTML-only emails with extra suspicion -
        they are easier to spoof confirmation links inside.
        """
        log_network_request("IMAP", f"{self.host}:{self.port}", f"search for '{subject_contains}'")
        logger.info(f"Checking inbox at {self.host} for '{subject_contains}'")

        results = []
        try:
            conn = imaplib.IMAP4_SSL(self.host, self.port)
            conn.login(self.user, self.password)
            conn.select("INBOX")

            search_query = f'(UNSEEN SUBJECT "{subject_contains}")'
            _, msg_nums = conn.search(None, search_query)

            for num in msg_nums[0].split():
                if not num:
                    continue
                _, msg_data = conn.fetch(num, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                text_body = ""
                html_body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ctype = part.get_content_type()
                        if ctype == "text/plain" and not text_body:
                            text_body = part.get_payload(decode=True).decode(errors="replace")
                        elif ctype == "text/html" and not html_body:
                            html_body = part.get_payload(decode=True).decode(errors="replace")
                else:
                    payload = msg.get_payload(decode=True).decode(errors="replace")
                    if msg.get_content_type() == "text/html":
                        html_body = payload
                    else:
                        text_body = payload

                # Prefer links from the plain-text part; only fall back
                # to HTML when the email is HTML-only.
                if text_body:
                    body = text_body
                    body_source = "text"
                else:
                    body = html_body
                    body_source = "html"

                links = URL_PATTERN.findall(body)

                results.append({
                    "subject": msg["Subject"],
                    "from_addr": msg["From"],
                    "body": body[:2000],
                    "links": links,
                    "uid": num.decode(),
                    "body_source": body_source,
                })

            conn.logout()
        except Exception as e:
            logger.error(f"IMAP error: {e}")

        return results

    def click_confirmation_link(self, url: str) -> bool:
        """Visit a confirmation URL using Playwright."""
        from playwright.sync_api import sync_playwright

        log_network_request("GET", url, "confirmation link click")
        logger.info(f"Clicking confirmation link: {url}")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                # Most confirmation pages just need to be loaded
                page.wait_for_timeout(2000)
                browser.close()
            return True
        except Exception as e:
            logger.error(f"Failed to click confirmation link: {e}")
            return False
