"""Generate removal demand letters as PDFs.

Two flavours:

* ``gdpr`` - Article 17 of the EU General Data Protection Regulation
  (the so-called right to erasure).
* ``ccpa`` - California Civil Code section 1798.105, the right to
  delete personal information held by a business.

The letters are intentionally short and plain. They are the kind of
letter a normal person could plausibly have written, which matters for
deliverability: aggressive legalese tends to get filed straight in the
spam folder.
"""

from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from privacyworm.playbook import Playbook
from privacyworm.profile import Profile


def _format_address(profile: Profile) -> str:
    if not profile.addresses:
        return ""
    a = profile.addresses[0]
    return f"{a.street}, {a.city}, {a.state} {a.zip}"


def _gdpr_lines(profile: Profile, playbook: Playbook) -> list[str]:
    name = f"{profile.name.first} {profile.name.last}"
    addr = _format_address(profile)
    dob = profile.dob or "[date of birth withheld]"
    reply_email = profile.emails[0] if profile.emails else "[your email]"
    return [
        date.today().isoformat(),
        "",
        f"To: {playbook.display_name}",
        "Re: Erasure request under Article 17 of the GDPR",
        "",
        f"Dear {playbook.display_name} privacy team,",
        "",
        "I am writing to demand erasure of all personal data you hold about "
        "me, under my right to erasure as set out in Article 17 of the EU "
        "General Data Protection Regulation. Continued processing for the "
        "purpose of publishing my name and arrest record is no longer "
        "necessary, and I object to it under Article 21.",
        "",
        "Identifying information so you can find my records:",
        f"  Full name: {name}",
        f"  Date of birth: {dob}",
        f"  Address: {addr}",
        "",
        "Please erase all of my data within thirty (30) days, as required "
        f"by Article 12(3), and confirm completion in writing to {reply_email}.",
        "",
        "If you do not comply, I will lodge a complaint with the relevant "
        "supervisory authority and pursue any other remedies available to me.",
        "",
        "Sincerely,",
        name,
    ]


def _ccpa_lines(profile: Profile, playbook: Playbook) -> list[str]:
    name = f"{profile.name.first} {profile.name.last}"
    addr = _format_address(profile)
    reply_email = profile.emails[0] if profile.emails else "[your email]"
    return [
        date.today().isoformat(),
        "",
        f"To: {playbook.display_name}",
        "Re: Right-to-delete request under the CCPA",
        "",
        f"Dear {playbook.display_name} privacy team,",
        "",
        "I am a California resident exercising my right to delete personal "
        "information that you have collected about me, as provided by "
        "California Civil Code section 1798.105.",
        "",
        "To verify my identity, here is enough to find my records:",
        f"  Full name: {name}",
        f"  Address: {addr}",
        "",
        "Please delete all personal information you hold about me and "
        "direct any service provider that received my information from "
        "you to do the same. You have forty-five (45) days to comply, "
        "per section 1798.130.",
        "",
        f"Confirm completion in writing to {reply_email}.",
        "",
        "Sincerely,",
        name,
    ]


def render_letter(
    profile: Profile, playbook: Playbook, law: str, out: Path
) -> Path:
    """Render a removal letter PDF. ``law`` must be ``gdpr`` or ``ccpa``."""
    law = law.lower()
    if law not in {"gdpr", "ccpa"}:
        raise ValueError(f"law must be 'gdpr' or 'ccpa', got {law!r}")

    out.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out),
        pagesize=LETTER,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )
    styles = getSampleStyleSheet()
    lines = _gdpr_lines(profile, playbook) if law == "gdpr" else _ccpa_lines(profile, playbook)
    story: list = []
    for line in lines:
        if line == "":
            story.append(Spacer(1, 0.15 * inch))
        else:
            story.append(Paragraph(line, styles["Normal"]))
    doc.build(story)
    return out
