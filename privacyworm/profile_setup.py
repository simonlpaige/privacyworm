"""The friendly profile interview used by ``privacyworm`` and ``privacyworm init``.

Asks for the minimum that makes broker searches work (name + where you
live), explains why each optional field helps, validates as it goes, and
shows a summary before anything is saved. Pass an existing profile to
edit it: every answer defaults to what's already there.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from privacyworm import ui
from privacyworm.profile import Address, InboxConfig, Name, Profile

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR",
}
STATE_CODES = set(US_STATES.values())

MIN_PASSPHRASE = 8


def normalize_state(raw: str) -> str | None:
    s = raw.strip().rstrip(".")
    if s.upper() in STATE_CODES:
        return s.upper()
    return US_STATES.get(s.lower())


def normalize_zip(raw: str) -> str | None:
    m = re.fullmatch(r"\s*(\d{5})(?:-?\d{4})?\s*", raw)
    return m.group(1) if m else None


def normalize_dob(raw: str) -> str | None:
    """Accept 1985-03-14, 03/14/1985, 3/14/85 or just 1985."""
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%B %d %Y", "%b %d %Y"):
        try:
            dt = datetime.strptime(raw.replace(",", ""), fmt)
        except ValueError:
            continue
        if dt.year > datetime.now().year:
            dt = dt.replace(year=dt.year - 100)
        return dt.strftime("%Y-%m-%d")
    if re.fullmatch(r"(19|20)\d{2}", raw):
        return raw
    return None


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def valid_email(raw: str) -> bool:
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw.strip()) is not None


def _split_list(raw: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,;]", raw) if p.strip()]


def _ask_required(prompt: str, default: str = "") -> str:
    while True:
        value = ui.ask(prompt, default)
        if value:
            return value
        ui.say("    This one's needed.")


def _ask_validated(prompt: str, fn, error: str, default: str = "", optional: bool = False) -> str | None:
    while True:
        raw = ui.ask(prompt, default)
        if not raw and optional:
            return None
        if not raw:
            ui.say("    This one's needed.")
            continue
        value = fn(raw)
        if value:
            return value
        ui.say(f"    {error}")


def _ask_address(existing: Address | None = None) -> Address:
    street = _ask_required("Street address", existing.street if existing else "")
    city = _ask_required("City", existing.city if existing else "")
    state = _ask_validated(
        "State", normalize_state, "Use the 2-letter code (like MO) or the full name.",
        existing.state if existing else "",
    )
    zip_code = _ask_validated(
        "ZIP code", normalize_zip, "That should be 5 digits.", existing.zip if existing else ""
    )
    return Address(street=street, city=city, state=state or "", zip=zip_code or "")


def _ask_phones(default: list[str]) -> list[str]:
    while True:
        raw = ui.ask("Phone numbers (comma-separated, optional)", ", ".join(default))
        phones: list[str] = []
        bad: list[str] = []
        for item in _split_list(raw):
            n = normalize_phone(item)
            (phones if n else bad).append(n or item)
        if not bad:
            return phones
        ui.say(f"    These don't look like US phone numbers: {', '.join(bad)}")


def _ask_emails(default: list[str]) -> list[str]:
    while True:
        raw = ui.ask("Email address(es) (comma-separated)", ", ".join(default))
        emails = _split_list(raw)
        bad = [e for e in emails if not valid_email(e)]
        if bad:
            ui.say(f"    These don't look like email addresses: {', '.join(bad)}")
            continue
        if not emails:
            ui.warn("No email means most opt-out forms can't be filled in for you.")
            if not ui.yes_no("Continue without one?", default=False):
                continue
        return emails


def _summary(p: Profile) -> None:
    ui.title("Here's what you entered")
    middle = f" {p.name.middle}" if p.name.middle else ""
    ui.say(f"  Name:       {p.name.first}{middle} {p.name.last}")
    if p.aliases:
        ui.say(f"  Also known: {', '.join(p.aliases)}")
    for i, a in enumerate(p.addresses):
        label = "Address:" if i == 0 else "Past:"
        ui.say(f"  {label:<11} {a.street}, {a.city}, {a.state} {a.zip}")
    ui.say(f"  Emails:     {', '.join(p.emails) or '-'}")
    ui.say(f"  Phones:     {', '.join(p.phones) or '-'}")
    ui.say(f"  Born:       {p.dob or '-'}")
    ui.say(f"  Relatives:  {', '.join(p.relatives) or '-'}")


def interview(existing: Profile | None = None) -> Profile:
    """Ask for the profile, validate it, confirm it. Returns a Profile."""
    e = existing
    while True:
        ui.title("Step 1 of 3 · Your name")
        ui.para("Exactly as it might appear on a people-search site.")
        first = _ask_required("First name", e.name.first if e else "")
        last = _ask_required("Last name", e.name.last if e else "")
        middle = ui.ask("Middle name or initial (optional)", (e.name.middle or "") if e else "")
        aliases = _split_list(ui.ask(
            "Other names you've used - maiden name, nickname (optional, comma-separated)",
            ", ".join(e.aliases) if e else "",
        ))

        ui.title("Step 2 of 3 · Where you live")
        ui.para(
            "Brokers organise listings by location, so this is how we find yours. "
            "Start with where you live now."
        )
        addresses: list[Address] = []
        old = list(e.addresses) if e else []
        addresses.append(_ask_address(old[0] if old else None))
        past = old[1:]
        if past:
            ui.say("  Past addresses on file:")
            for a in past:
                ui.say(f"    - {a.street}, {a.city}, {a.state} {a.zip}")
            if ui.yes_no("Keep these?", default=True):
                addresses.extend(past)
        while ui.yes_no("Add a past address? (helps catch older listings)", default=False):
            addresses.append(_ask_address())

        ui.title("Step 3 of 3 · Contact details")
        ui.para(
            "Opt-out forms need an email, and brokers send confirmation links there. "
            "Tip: a separate address or alias works fine. Everything else here is optional "
            "but helps tell you apart from people with the same name."
        )
        emails = _ask_emails(list(e.emails) if e else [])
        phones = _ask_phones(list(e.phones) if e else [])
        dob = _ask_validated(
            "Date of birth (optional, e.g. 1985-03-14 or just 1985)",
            normalize_dob,
            "Try 1985-03-14, 03/14/1985, or just the year.",
            (e.dob or "") if e else "",
            optional=True,
        )
        relatives = _split_list(ui.ask(
            "Names of close relatives (optional, comma-separated)",
            ", ".join(e.relatives) if e else "",
        ))

        profile = Profile(
            name=Name(first=first, last=last, middle=middle or None),
            aliases=aliases,
            addresses=addresses,
            dob=dob,
            phones=phones,
            emails=emails,
            relatives=relatives,
            inbox=e.inbox if e else None,
            attested_at=e.attested_at if e else None,
        )
        _summary(profile)
        if ui.yes_no("Does that look right?", default=True):
            break
        e = profile  # go round again with these answers as defaults

    if not profile.attested_at:
        ui.title("One promise")
        ui.para(
            "PrivacyWorm sends removal requests in this person's name. Only use it for "
            "your own information, or for someone who has asked you to act for them."
        )
        if not ui.yes_no("This is my info, or I'm authorised to act for this person", default=True):
            raise SystemExit("Okay - nothing was saved.")
        profile.attested_at = datetime.now(timezone.utc).isoformat()
    return profile


def ask_new_passphrase() -> str:
    """Ask for a new passphrase twice. Enforces a sensible minimum."""
    import getpass

    ui.para(
        "Pick a passphrase to lock your info. You'll type it each time you open "
        "PrivacyWorm. A few words strung together are easy to remember and hard "
        "to guess. If you forget it, you'll just need to enter your details again."
    )
    while True:
        try:
            first = getpass.getpass(ui.style("  New passphrase: ", bold=True))
            second = getpass.getpass(ui.style("  Type it again: ", bold=True))
        except EOFError:
            raise SystemExit("No passphrase entered - nothing was saved.") from None
        if first != second:
            ui.say("    Those didn't match. Let's try again.")
            continue
        if len(first) < MIN_PASSPHRASE:
            ui.say(f"    Please use at least {MIN_PASSPHRASE} characters.")
            continue
        return first


def ask_inbox(existing: InboxConfig | None = None) -> InboxConfig | None:
    """Set up IMAP access so confirmation links can be found automatically."""
    import getpass

    ui.title("Automatic email confirmations (optional)")
    ui.para(
        "Some brokers email you a link you must click to finish the removal. "
        "PrivacyWorm can find those emails for you and show you each link before "
        "opening it. For Gmail, Outlook, iCloud or Yahoo you'll need an 'app password' "
        "(search your provider's help for 'app password'). It's saved inside your "
        "encrypted profile."
    )
    presets = {
        "gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com",
        "outlook.com": "outlook.office365.com", "hotmail.com": "outlook.office365.com",
        "live.com": "outlook.office365.com", "icloud.com": "imap.mail.me.com",
        "me.com": "imap.mail.me.com", "yahoo.com": "imap.mail.yahoo.com",
        "fastmail.com": "imap.fastmail.com",
    }
    user = _ask_validated(
        "Email address to check", lambda s: s.strip() if valid_email(s) else None,
        "That doesn't look like an email address.",
        existing.user if existing else "",
    )
    assert user is not None  # nosec B101 - _ask_validated loops until valid
    domain = user.split("@", 1)[1].lower()
    host = ui.ask("Mail server (IMAP)", existing.host if existing else presets.get(domain, f"imap.{domain}"))
    port_raw = ui.ask("Port", str(existing.port) if existing else "993")
    try:
        password = getpass.getpass(ui.style("  App password (input hidden): ", bold=True))
    except EOFError:
        password = ""
    return InboxConfig(
        host=host,
        port=int(port_raw) if port_raw.isdigit() else 993,
        user=user,
        password=password or (existing.password if existing else None),
    )
