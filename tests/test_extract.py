"""Tests for the playbook extract layer."""

from pathlib import Path

from privacyworm.extract import extract_listings_from_html
from privacyworm.playbook import get_playbook

FIXTURES = Path(__file__).parent / "fixtures"


def test_spokeo_fixture_yields_two_listings():
    pb = get_playbook("spokeo")
    assert pb is not None
    html = (FIXTURES / "spokeo_results.html").read_text(encoding="utf-8")
    listings = extract_listings_from_html(html, pb.search.listing_selectors, pb.extract)
    assert len(listings) == 2
    first = listings[0]
    assert first["full_name"] == "Simon L Paige"
    assert first["city_state"] == "Kansas City, MO"
    assert first["listing_url"] == "/Simon-Paige/Kansas-City-MO/abc123"


def test_extract_handles_missing_selectors_gracefully():
    html = "<html><body><div class='r'><span class='name'>Jane Doe</span></div></body></html>"
    spec = {"name": "span.name::text", "missing": "div.nope::text"}
    out = extract_listings_from_html(html, ["div.r"], spec)
    assert out == [{"name": "Jane Doe", "missing": None}]


def test_extract_supports_many():
    html = (
        "<html><body><div class='r'>"
        "<span class='rel'>Alice</span>"
        "<span class='rel'>Bob</span>"
        "</div></body></html>"
    )
    spec = {"relatives": {"selector": "span.rel::text", "many": True}}
    out = extract_listings_from_html(html, ["div.r"], spec)
    assert out == [{"relatives": ["Alice", "Bob"]}]
