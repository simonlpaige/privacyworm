"""Read broker replies and decide what each one means.

Every reply is matched to the request it answers (by email threading,
our ``[ref PW-XXXX]`` tag, or the sender's domain) and sorted into:

  done        "we deleted / suppressed your data"
  not_found   "we have no records about you"           (also a win)
  verify      "click this link to confirm"            -> clicked automatically,
                                                          only if the link is on
                                                          the broker's own domain
  needs_you   "use our web form" / "send ID" / unclear  -> your short to-do list
  refused     "only for California residents" etc.     -> escalation continues
  ack         "we received your request"              -> keep waiting
  bounced     the address doesn't work                 -> to-do: use their website

Keyword rules are deliberately simple and conservative. Anything the
rules aren't sure about lands on the to-do list rather than being
guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr

from privacyworm.registry import registered_domain

REF_RE = re.compile(r"\bPW-[A-Z0-9]{6}\b")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

# Ticketing / privacy-request platforms brokers commonly reply through.
# Matching on these is fine for *reading*; we never auto-click their links.
HELPDESK_DOMAINS = {
    "zendesk.com", "freshdesk.com", "helpscoutapp.com", "intercom-mail.com", "onetrust.com",
    "trustarc.com", "transcend.io", "ketch.com", "salesforce.com", "hubspot.com",
    "mytransponder.com", "osano.com", "datagrail.io", "securiti.ai", "wirewheel.io",
}

BOUNCE_SENDERS = ("mailer-daemon", "postmaster", "mail delivery")
BOUNCE_PHRASES = (
    "delivery has failed", "undeliverable", "address not found", "could not be delivered",
    "delivery status notification (failure)", "user unknown", "does not exist", "mailbox unavailable",
    "recipient address rejected", "message not delivered",
)
NOT_FOUND = (
    "unable to locate", "could not locate", "couldn't locate", "no records", "no record of",
    "not able to find", "unable to find", "could not find", "couldn't find", "did not find",
    "do not have any", "don't have any", "does not have any", "no personal information",
    "no data associated", "not find any", "no information about you", "no matching",
    "not in our database", "no results",
)
DONE = (
    "has been deleted", "have been deleted", "have deleted", "we deleted", "been removed",
    "have removed", "we removed", "has been completed", "request is complete", "request has been completed",
    "completed your request", "processed your deletion", "processed your request to delete",
    "has been processed", "opted out", "opt-out has been", "added to our suppression",
    "added you to our suppression", "on our suppression list", "has been suppressed", "will no longer",
    "successfully deleted", "successfully removed", "successfully processed",
)
NEEDS_FORM = (
    "web form", "webform", "online form", "request form", "privacy portal", "privacy center",
    "please submit your request", "submit a request", "please visit", "please use the",
    "please complete the", "fill out", "verify your identity", "verification of your identity",
    "government-issued", "government issued", "photo id", "driver's license", "drivers license",
    "notarized", "authorized agent", "proof of residency", "last four", "last 4",
)
REFUSED = (
    "california residents", "only available to residents", "not a resident",
    "residents of certain states", "residents of states", "not required to", "does not apply",
    "do not apply to you", "unable to process your request because", "cannot honor",
    "not able to honor", "we decline", "deny your request", "denied",
)
ACK = (
    "received your request", "have received your", "request has been received", "ticket",
    "will respond within", "will be in touch", "is being processed", "we are processing",
    "within 45 days", "within 30 days", "thank you for contacting", "auto-reply", "automatic reply",
)
VERIFY_WORDS = ("verify", "confirm", "validation", "validate")


@dataclass
class Verdict:
    kind: str  # done | not_found | verify | needs_you | refused | ack | bounced
    note: str
    link: str | None = None


def body_text(msg: EmailMessage) -> str:
    """Plain text of a message, falling back to stripped HTML."""
    part = msg.get_body(preferencelist=("plain",))
    if part is not None:
        try:
            return part.get_content()
        except (LookupError, ValueError):
            pass
    part = msg.get_body(preferencelist=("html",))
    if part is not None:
        try:
            html = part.get_content()
        except (LookupError, ValueError):
            return ""
        # Keep href targets visible, then strip tags.
        html = re.sub(r'<a\s[^>]*href="([^"]+)"[^>]*>', r" \1 ", html, flags=re.I)
        html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"[ \t]+", " ", text)
    return ""


def strip_quoted(text: str) -> str:
    """Drop the quoted copy of our own letter so its words don't count."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(">"):
            continue
        if re.match(r"^On .+ wrote:$", s) or s.startswith("-----Original Message") or s.startswith("From: "):
            break
        if "To the privacy team at" in s:  # our letter pasted inline without quoting
            break
        out.append(line)
    return "\n".join(out)


def _has(text: str, phrases) -> str | None:
    for p in phrases:
        if p in text:
            return p
    return None


def classify(msg: EmailMessage, broker_domains: set[str]) -> Verdict:
    sender = parseaddr(str(msg.get("From", "")))[1].lower()
    subject = str(msg.get("Subject", "")).lower()
    raw = body_text(msg)
    text = strip_quoted(raw).lower()
    links = URL_RE.findall(strip_quoted(raw))

    if any(b in sender for b in BOUNCE_SENDERS) or _has(subject, BOUNCE_PHRASES):
        return Verdict("bounced", "Their privacy address doesn't accept mail.")
    if (p := _has(text, NOT_FOUND)):
        return Verdict("not_found", f'They say they have no records about you ("{p}").')
    if (p := _has(text, DONE)):
        return Verdict("done", f'They confirmed it ("{p}").')

    own_links = [u for u in links if registered_domain(u) in broker_domains]
    if own_links and _has(text, VERIFY_WORDS) and not _has(text, NEEDS_FORM):
        verify = [u for u in own_links if _has(u.lower(), VERIFY_WORDS + ("token", "request"))]
        if verify:
            return Verdict("verify", "They asked you to confirm by clicking a link.", verify[0])

    if (p := _has(text, NEEDS_FORM)):
        link = own_links[0] if own_links else (links[0] if links else None)
        return Verdict("needs_you", f'They want you to use their own process ("{p}").', link)
    if (p := _has(text, REFUSED)):
        return Verdict("refused", f'They refused ("{p}").')
    if _has(text, ACK) or _has(subject, ACK):
        return Verdict("ack", "They acknowledged the request.")
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")[:120]
    return Verdict("needs_you", f'They replied, and it needs a human read: "{first}"', links[0] if links else None)


def references(msg: EmailMessage) -> set[str]:
    out = set()
    for header in ("In-Reply-To", "References"):
        out.update(re.findall(r"<[^>]+>", str(msg.get(header, ""))))
    return out


def find_ref(msg: EmailMessage) -> str | None:
    m = REF_RE.search(str(msg.get("Subject", "")))
    if m:
        return m.group(0)
    m = REF_RE.search(body_text(msg)[:20000])
    return m.group(0) if m else None


def sender_domain(msg: EmailMessage) -> str:
    return registered_domain(parseaddr(str(msg.get("From", "")))[1].rsplit("@", 1)[-1])
