"""Confidence scoring for scraped broker listings.

A listing card from a broker (raw text and any URL bits we managed to scrape)
gets compared against the user's profile. The output tells the rest of the
system how much we trust the match, so the opt-out flow can stop blindly
filing requests off a first-and-last-name collision.
"""

import re
from datetime import date, datetime
from typing import Optional

from privacyworm.profile import Profile

HIGH_THRESHOLD = 70
MEDIUM_THRESHOLD = 45


def normalize_name(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Handles 'Simon L. Paige' vs 'Simon Paige' - middle initials and periods
    get flattened out so equality checks line up.
    """
    if not s:
        return ""
    lowered = s.lower()
    cleaned = re.sub(r"[^\w\s]", " ", lowered)
    return " ".join(cleaned.split())


def _normalize_text(s: str) -> str:
    """Normalize listing text the same way as names, for whole-text searching."""
    return normalize_name(s)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _name_in_text(first: str, last: str, text: str) -> bool:
    """True when both first and last appear in the normalized text in order."""
    norm_text = _normalize_text(text)
    norm_first = normalize_name(first)
    norm_last = normalize_name(last)
    if not norm_first or not norm_last:
        return False
    pattern = rf"\b{re.escape(norm_first)}\b.*\b{re.escape(norm_last)}\b"
    return re.search(pattern, norm_text) is not None


def _parse_dob_year(dob: str) -> Optional[int]:
    """Pull a 4-digit year out of a DOB string in any reasonable format."""
    if not dob:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y"):
        try:
            return datetime.strptime(dob.strip(), fmt).year
        except ValueError:
            continue
    match = re.search(r"\b(19|20)\d{2}\b", dob)
    return int(match.group(0)) if match else None


def _extract_age_from_text(text: str) -> Optional[int]:
    """Find an age-like number in scraped text. Looks for 'Age 42' or 'age: 42'."""
    match = re.search(r"\bage[\s:]*?(\d{1,3})\b", text, re.IGNORECASE)
    if match:
        age = int(match.group(1))
        if 0 < age < 120:
            return age
    return None


def score_listing(listing_text: str, profile: Profile) -> dict:
    """Score how likely a scraped listing is to be the user.

    Returns a dict: score (0-100), confidence ('high'/'medium'/'low'),
    matched_fields (list).

    Score bands: high >= 70, medium >= 45, low < 45.
    """
    text = listing_text or ""
    norm_text = _normalize_text(text)
    matched: list[str] = []
    score = 0

    if _name_in_text(profile.name.first, profile.name.last, text):
        score += 40
        matched.append("full_name")

    address_cities = {normalize_name(a.city) for a in profile.addresses if a.city}
    address_states = {normalize_name(a.state) for a in profile.addresses if a.state}
    address_zips = {a.zip.strip() for a in profile.addresses if a.zip}

    if any(c and c in norm_text for c in address_cities):
        score += 20
        matched.append("city")

    if any(s and re.search(rf"\b{re.escape(s)}\b", norm_text) for s in address_states):
        score += 15
        matched.append("state")

    if any(z and z in text for z in address_zips):
        score += 15
        matched.append("zip")

    text_digits = _digits(text)
    profile_phone_digits = [_digits(p)[-10:] for p in profile.phones if _digits(p)]
    if any(p and len(p) == 10 and p in text_digits for p in profile_phone_digits):
        score += 25
        matched.append("phone")

    for relative in profile.relatives:
        rel_norm = normalize_name(relative)
        if rel_norm and rel_norm in norm_text:
            score += 10
            matched.append("relative")
            break

    dob_year = _parse_dob_year(profile.dob or "")
    if dob_year:
        listing_age = _extract_age_from_text(text)
        if listing_age is not None:
            today = date.today()
            expected_age = today.year - dob_year
            if abs(expected_age - listing_age) <= 3:
                score += 15
                matched.append("age")

    score = min(score, 100)
    if score >= HIGH_THRESHOLD:
        confidence = "high"
    elif score >= MEDIUM_THRESHOLD:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "score": score,
        "confidence": confidence,
        "matched_fields": matched,
    }
