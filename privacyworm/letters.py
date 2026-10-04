"""Deletion-request letters that work wherever you live.

If your state or country gives you a legal right to deletion, the letter
cites it. If it doesn't (Missouri, for example, has no such law as of
2026), the letter still asks firmly and accurately: every company in our
list is a registered data broker with a published deletion process, most
already honor requests nationwide, and if they won't, the escalation
ladder ends in complaints to the FTC and your state attorney general.

The letters never claim a legal right you don't have. That keeps them
honest and keeps you out of trouble.
"""

from __future__ import annotations

import textwrap

from privacyworm.profile import Profile

# US states with comprehensive consumer privacy laws that include a right
# to delete (as of 2026). Name of the law only - no section numbers we
# can't keep current.
STATE_LAWS = {
    "CA": "the California Consumer Privacy Act (Cal. Civ. Code 1798.105) and the Delete Act",
    "VA": "the Virginia Consumer Data Protection Act",
    "CO": "the Colorado Privacy Act",
    "CT": "the Connecticut Data Privacy Act",
    "UT": "the Utah Consumer Privacy Act",
    "IA": "the Iowa Consumer Data Protection Act",
    "IN": "the Indiana Consumer Data Protection Act",
    "TN": "the Tennessee Information Protection Act",
    "MT": "the Montana Consumer Data Privacy Act",
    "OR": "the Oregon Consumer Privacy Act",
    "TX": "the Texas Data Privacy and Security Act",
    "DE": "the Delaware Personal Data Privacy Act",
    "NH": "New Hampshire's consumer data privacy law (RSA 507-H)",
    "NJ": "the New Jersey Data Privacy Act",
    "KY": "the Kentucky Consumer Data Protection Act",
    "NE": "the Nebraska Data Privacy Act",
    "MD": "the Maryland Online Data Privacy Act",
    "MN": "the Minnesota Consumer Data Privacy Act",
    "RI": "the Rhode Island Data Transparency and Privacy Protection Act",
}

COUNTRY_LAWS = {
    "EU": "Article 17 of the EU General Data Protection Regulation (right to erasure)",
    "UK": "Article 17 of the UK GDPR (right to erasure)",
    "CA-COUNTRY": "Canada's Personal Information Protection and Electronic Documents Act (PIPEDA)",
}

FTC_COMPLAINT_URL = "https://reportfraud.ftc.gov/"
FIND_YOUR_AG_URL = "https://www.naag.org/find-my-ag/"


def legal_basis(state: str | None) -> str | None:
    """The law to cite for this user, or None when there isn't one."""
    if not state:
        return None
    return STATE_LAWS.get(state.strip().upper()) or COUNTRY_LAWS.get(state.strip().upper())


def full_name(p: Profile) -> str:
    middle = f" {p.name.middle}" if p.name.middle else ""
    return f"{p.name.first}{middle} {p.name.last}"


def identifiers(p: Profile) -> list[str]:
    """The details a broker needs to find (and delete) your records."""
    lines = [f"Full name: {full_name(p)}"]
    if p.aliases:
        lines.append(f"Other names: {', '.join(p.aliases)}")
    for i, a in enumerate(p.addresses):
        label = "Current address" if i == 0 else "Previous address"
        lines.append(f"{label}: {a.street}, {a.city}, {a.state} {a.zip}")
    if p.phones:
        lines.append(f"Phone: {', '.join(p.phones)}")
    if p.emails:
        lines.append(f"Email: {', '.join(p.emails)}")
    # Date of birth is left out on purpose: name + addresses + phone/email
    # is enough to match, and we'd rather not hand a DOB to 700 companies
    # that may not have it yet.
    return lines


def subject(p: Profile, ref: str, stage: int = 0) -> str:
    base = f"Request to delete my personal information - {full_name(p)} [ref {ref}]"
    return base if stage == 0 else f"Re: {base}"


def _block(lines: list[str]) -> str:
    return "\n".join(f"  {line}" for line in lines)


def initial(p: Profile, broker_name: str, ref: str) -> str:
    state = p.addresses[0].state if p.addresses else None
    law = legal_basis(state)
    if law:
        basis = (
            f"I am a resident of {state.upper() if state else 'a US state'}. This is a request "
            f"under {law} that you delete all personal information you hold about me, and that "
            "you stop selling or sharing it."
        )
        deadline = "Please confirm completion within 45 days, as the law requires."
    else:
        basis = (
            "I am asking you to delete all personal information you hold about me and to stop "
            "selling or sharing it. You are registered as a data broker and publish a process for "
            "consumer deletion requests; please apply it to me on the same terms you offer "
            "residents of states with deletion laws."
        )
        deadline = "Please confirm completion within 45 days."
    basis = textwrap.fill(basis, 72)
    return f"""To the privacy team at {broker_name},

{basis}

Specifically, I request that you:
  1. Delete all personal information about me, including any people-search
     profiles, marketing records and inferences.
  2. Stop selling or sharing my information, and tell any third parties you
     sold or shared it to that I have made this request.
  3. Add me to your suppression list so my information is not collected again.

To help you find my records:
{_block(identifiers(p))}

Use these details only to locate and delete my information - do not add
them to your database. If you need anything else to process this request,
reply to this email. {deadline}

Thank you,
{full_name(p)}
"""


def follow_up(p: Profile, broker_name: str, ref: str, days: int) -> str:
    return f"""To the privacy team at {broker_name},

I sent a request {days} days ago (reference {ref}) asking you to delete all
personal information you hold about me and to stop selling or sharing it.
I have not received confirmation that it was completed.

Please complete it and confirm by reply. My details:
{_block(identifiers(p))}

Thank you,
{full_name(p)}
"""


def final_notice(p: Profile, broker_name: str, ref: str, days: int) -> str:
    state = p.addresses[0].state if p.addresses else "my state"
    return f"""To the privacy team at {broker_name},

This is my third request (reference {ref}, first sent {days} days ago) that
you delete all personal information you hold about me and stop selling or
sharing it. I have had no confirmation.

If I don't receive confirmation within 15 days, I will file complaints with
the Federal Trade Commission and the {state} Attorney General describing a
registered data broker that did not act on a consumer's deletion request.

My details:
{_block(identifiers(p))}

{full_name(p)}
"""


def complaint(p: Profile, rows: list[dict]) -> str:
    """One consolidated complaint covering every broker that ignored or refused."""
    state = p.addresses[0].state if p.addresses else ""
    lines = []
    for r in rows:
        first = (r.get("first_sent_at") or "")[:10]
        why = "refused" if r.get("status") == "refused" else "did not respond after three requests"
        lines.append(f"  - {r['broker_name']} ({r['to_addr']}): first asked {first}, {why}")
    return f"""Complaint: data brokers not honoring deletion requests

I am a consumer{' in ' + state if state else ''}. I asked each company below, by email
to the privacy address it lists in the California data broker registry, to
delete my personal information and stop selling it. I followed up twice
over at least 60 days. Each one ignored or refused the request.

{chr(10).join(lines)}

I have copies of every request and reply and can provide them.

{full_name(p)}
{p.emails[0] if p.emails else ''}
"""
