"""Tests for the network-log redaction logic in privacyworm.config."""

from privacyworm.config import scrub_pii


def test_strips_query_string():
    raw = "https://www.spokeo.com/search?first=Simon&last=Paige"
    assert scrub_pii(raw) == "https://www.spokeo.com/search"


def test_strips_fragment():
    raw = "https://www.spokeo.com/optout#email"
    assert scrub_pii(raw) == "https://www.spokeo.com/optout"


def test_redacts_namey_path_segment():
    raw = "https://www.spokeo.com/Simon-Paige/MO"
    assert scrub_pii(raw) == "https://www.spokeo.com/[REDACTED]/MO"


def test_redacts_full_name_with_middle_initial():
    raw = "https://www.spokeo.com/Simon-L-Paige/Kansas-City-MO"
    out = scrub_pii(raw)
    assert "Simon" not in out
    assert "Paige" not in out
    assert out.startswith("https://www.spokeo.com/")


def test_keeps_state_codes_and_short_words():
    raw = "https://www.spokeo.com/optout/MO/12345"
    assert scrub_pii(raw) == "https://www.spokeo.com/optout/MO/12345"


def test_handles_empty_input():
    assert scrub_pii("") == ""


def test_handles_relative_paths():
    raw = "/optout?email=simon@example.com"
    assert scrub_pii(raw) == raw
