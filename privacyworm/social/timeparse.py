"""Tiny parser for relative time spans like ``1y``, ``30d``, ``6m``, ``2w``."""

import re
from datetime import datetime, timedelta, timezone

PERIOD_RE = re.compile(r"^\s*(\d+)\s*([dwmy])\s*$", re.IGNORECASE)


def parse_period(value: str) -> timedelta:
    """Parse strings like ``1y`` (year), ``30d`` (days), ``6m`` (months), ``2w`` (weeks).

    Months are taken as 30 days and years as 365 days. That is good enough
    for "older-than" cutoffs; nobody picks one of these to the day.
    """
    m = PERIOD_RE.match(value or "")
    if not m:
        raise ValueError(
            f"Could not parse period '{value}'. Try '30d', '6m', '1y', '2w'."
        )
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "d":
        return timedelta(days=n)
    if unit == "w":
        return timedelta(weeks=n)
    if unit == "m":
        return timedelta(days=n * 30)
    if unit == "y":
        return timedelta(days=n * 365)
    raise ValueError(f"Unknown period unit: {unit!r}")


def parse_iso_date(value: str) -> datetime:
    """Parse a YYYY-MM-DD date as midnight UTC."""
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
