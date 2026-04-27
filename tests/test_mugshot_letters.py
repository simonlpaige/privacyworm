"""Tests for mugshot removal letter PDF generation."""

import tempfile
from pathlib import Path

import pytest

from privacyworm.mugshot.letters import render_letter
from privacyworm.playbook import load_playbook
from privacyworm.profile import Address, Name, Profile

MUGSHOT_DIR = Path(__file__).parent.parent / "playbooks" / "mugshots"


def _profile() -> Profile:
    return Profile(
        name=Name(first="Jane", last="Doe", middle="Q"),
        addresses=[Address(street="1 Main St", city="Austin", state="TX", zip="78701")],
        emails=["jane.doe@example.com"],
        dob="1990-01-01",
    )


def _playbook():
    return load_playbook(MUGSHOT_DIR / "mugshots.com.yaml")


def test_render_ccpa_letter_writes_pdf():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "letter.pdf"
        render_letter(_profile(), _playbook(), "ccpa", out)
        assert out.exists()
        head = out.read_bytes()[:4]
        assert head == b"%PDF", f"Output is not a PDF: {head!r}"


def test_render_gdpr_letter_writes_pdf():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "letter.pdf"
        render_letter(_profile(), _playbook(), "gdpr", out)
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"


def test_unknown_law_rejected():
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ValueError):
            render_letter(_profile(), _playbook(), "telepathy", Path(td) / "x.pdf")


def test_render_creates_parent_dir():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "subdir" / "nested" / "letter.pdf"
        render_letter(_profile(), _playbook(), "ccpa", out)
        assert out.exists()
