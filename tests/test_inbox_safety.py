"""Tests for confirmation-link allowlists and the processed-emails table."""

import tempfile
from pathlib import Path

import pytest

from privacyworm.playbook import Playbook
from privacyworm.runner import _link_domain_allowed, _link_path_allowed
from privacyworm.state import StateDB


def _pb(domains=None, path_contains=None):
    return Playbook(
        broker="x",
        display_name="X",
        homepage="https://www.x.com",
        last_updated="2026-04-27",
        search={"url_template": "https://www.x.com/{first}", "method": "browser"},
        opt_out={
            "method": "web_form",
            "url": "https://www.x.com/optout",
            "form": {},
            "confirmation_domains": domains or [],
            "confirmation_path_contains": path_contains or [],
        },
    )


def test_domain_allowlist_explicit_match():
    pb = _pb(domains=["x.com"])
    assert _link_domain_allowed("https://confirm.x.com/click?id=1", pb) is True


def test_domain_allowlist_blocks_off_domain():
    pb = _pb(domains=["x.com"])
    assert _link_domain_allowed("https://evil.com/click?id=1", pb) is False


def test_domain_allowlist_falls_back_to_homepage():
    pb = _pb(domains=[])
    assert _link_domain_allowed("https://www.x.com/confirm", pb) is True
    assert _link_domain_allowed("https://evil.com/confirm", pb) is False


def test_path_required_substrings_match():
    pb = _pb(path_contains=["/optout/confirm"])
    assert _link_path_allowed("https://www.x.com/optout/confirm/abc", pb) is True
    assert _link_path_allowed("https://www.x.com/something/else", pb) is False


def test_path_check_skipped_when_no_required():
    pb = _pb(path_contains=[])
    assert _link_path_allowed("https://www.x.com/whatever", pb) is True


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    state = StateDB(db_path=path)
    yield state
    state.close()
    path.unlink(missing_ok=True)


def test_processed_emails_dedup(db):
    assert db.email_already_processed("spokeo", "12345") is False
    db.mark_email_processed("spokeo", "12345")
    assert db.email_already_processed("spokeo", "12345") is True
    # Different broker / different uid don't collide.
    assert db.email_already_processed("whitepages", "12345") is False
    assert db.email_already_processed("spokeo", "67890") is False
