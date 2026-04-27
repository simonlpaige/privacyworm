"""Tests for the period parser used by `social delete`/`social overwrite`."""

from datetime import timedelta

import pytest

from privacyworm.social.timeparse import parse_iso_date, parse_period


def test_parse_days():
    assert parse_period("30d") == timedelta(days=30)


def test_parse_weeks():
    assert parse_period("2w") == timedelta(weeks=2)


def test_parse_months_is_30_days():
    assert parse_period("6m") == timedelta(days=180)


def test_parse_years_is_365_days():
    assert parse_period("1y") == timedelta(days=365)


def test_parse_with_whitespace():
    assert parse_period("  3 d  ") == timedelta(days=3)


def test_uppercase_unit():
    assert parse_period("4Y") == timedelta(days=4 * 365)


@pytest.mark.parametrize("bad", ["", "abc", "1x", "1.5d", "-1y", "1"])
def test_parse_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_period(bad)


def test_parse_iso_date_is_utc():
    d = parse_iso_date("2024-01-15")
    assert d.year == 2024 and d.month == 1 and d.day == 15
    assert d.tzinfo is not None
    assert d.utcoffset().total_seconds() == 0
