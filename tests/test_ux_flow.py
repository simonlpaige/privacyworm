"""Tests for the guided-mode building blocks: safe URLs, assisted
opt-outs, removal tracking, input normalisation and reminder timing."""

import io
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from privacyworm import desktop
from privacyworm.brokers.base import BaseBroker, build_search_url
from privacyworm.brokers.email import build_mailto
from privacyworm.playbook import PLAYBOOKS_DIR, Playbook, get_playbook, load_playbook
from privacyworm.profile import Address, Name, Profile
from privacyworm.profile_setup import (
    normalize_dob,
    normalize_phone,
    normalize_state,
    normalize_zip,
)
from privacyworm import runner
from privacyworm.runner import file_optouts, review_listings, scan_broker_report
from privacyworm.state import StateDB


def _profile(**kw) -> Profile:
    base = dict(
        name=Name(first="Mary Ann", last="O'Brien"),
        addresses=[Address(street="x", city="Kansas City", state="mo", zip="64113")],
        emails=["m@example.com"],
    )
    base.update(kw)
    return Profile(**base)


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    state = StateDB(db_path=path)
    yield state
    state.close()
    path.unlink(missing_ok=True)


# -- search URLs ---------------------------------------------------------------

def test_search_url_is_encoded():
    url = build_search_url("https://x.com/{first}-{last}/{state}?c={city}", _profile())
    assert url == "https://x.com/Mary%20Ann-O%27Brien/MO?c=Kansas%20City"


def test_search_url_rejects_attribute_access():
    with pytest.raises(ValueError):
        build_search_url("https://x.com/{first.__class__}", _profile())


def test_playbook_rejects_unknown_placeholder():
    data = load_playbook(PLAYBOOKS_DIR / "spokeo.yaml").model_dump()
    data["search"]["url_template"] = "https://www.spokeo.com/{first.__init__.__globals__}"
    with pytest.raises(ValueError):
        Playbook(**data)


def test_playbooks_ship_with_package_layout():
    # Works in a source checkout (repo-root playbooks/) and in a wheel
    # (privacyworm/playbooks/). Either way there must be brokers to scan.
    assert len(list(PLAYBOOKS_DIR.glob("*.yaml"))) >= 10
    assert (PLAYBOOKS_DIR / "mugshots").is_dir()
    assert (PLAYBOOKS_DIR / "social").is_dir()


# -- normalisation -------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("mo", "MO"), ("Missouri", "MO"), ("new york", "NY"), ("XX", None),
])
def test_normalize_state(raw, expected):
    assert normalize_state(raw) == expected


def test_normalize_misc():
    assert normalize_zip("64113-1234") == "64113"
    assert normalize_zip("641") is None
    assert normalize_phone("(816) 555-1234") == "816-555-1234"
    assert normalize_phone("+1 816 555 1234") == "816-555-1234"
    assert normalize_phone("555-1234") is None
    assert normalize_dob("03/14/1985") == "1985-03-14"
    assert normalize_dob("1985") == "1985"
    assert normalize_dob("yesterday") is None


# -- scan reports: removal tracking ---------------------------------------------

class _FakeBroker(BaseBroker):
    results: list = []
    status = "ok"

    def scan(self):
        self.scan_status = self.status
        return list(self.results)

    def file_optout(self, listing, dry_run=False, assist=None):
        return {"success": True, "method": "fake", "details": "ok"}


def _scan_with(monkeypatch, db, results, status="ok"):
    _FakeBroker.results = results
    _FakeBroker.status = status
    monkeypatch.setattr(runner, "_make_broker", lambda pb, prof, headed=False: _FakeBroker(pb, prof))
    return scan_broker_report(get_playbook("spokeo"), _profile(), db)


def test_listing_marked_removed_then_reappeared(monkeypatch, db):
    hit = {"listing_url": "https://spokeo.com/a", "matched_name": "Mary Ann O'Brien", "raw_snippet": "Kansas City MO"}
    r = _scan_with(monkeypatch, db, [hit])
    assert r["new"] == 1
    row = db.find_listing("spokeo", "https://spokeo.com/a")
    db.update_listing_status(row["id"], "optout_submitted")

    r = _scan_with(monkeypatch, db, [])
    assert r["gone"] == 1
    assert db.find_listing("spokeo", "https://spokeo.com/a")["status"] == "removed"

    r = _scan_with(monkeypatch, db, [hit])
    assert r["reappeared"] == 1
    assert db.find_listing("spokeo", "https://spokeo.com/a")["status"] == "reappeared"


def test_blocked_scan_changes_nothing(monkeypatch, db):
    hit = {"listing_url": "https://spokeo.com/a", "matched_name": "Mary Ann O'Brien"}
    _scan_with(monkeypatch, db, [hit])
    row = db.find_listing("spokeo", "https://spokeo.com/a")
    db.update_listing_status(row["id"], "optout_submitted")
    db.conn.execute("DELETE FROM rescans")
    r = _scan_with(monkeypatch, db, [], status="blocked")
    assert r["status"] == "blocked"
    assert r["gone"] == 0
    assert db.find_listing("spokeo", "https://spokeo.com/a")["status"] == "optout_submitted"
    assert db.next_rescan_at() is None  # stays due


# -- assisted opt-outs -----------------------------------------------------------

def test_email_optout_opens_mail_draft_when_no_smtp(db, monkeypatch):
    seen = []
    lid = db.add_listing(broker="radaris", listing_url="https://radaris.com/p/1")
    db.update_listing_status(lid, "approved")
    outcomes = file_optouts(
        _profile(), db, approved_only=True, assist=lambda info: seen.append(info) or "done"
    )
    assert outcomes[0]["success"]
    assert seen[0]["kind"] == "email"
    assert seen[0]["mailto"].startswith("mailto:support@radaris.com?subject=")
    assert db.find_listing("radaris", "https://radaris.com/p/1")["status"] == "optout_submitted"


def test_manual_optout_assist_skip_keeps_listing(db):
    lid = db.add_listing(broker="mugshots.com", listing_url="https://mugshots.com/x")
    db.update_listing_status(lid, "approved")
    outcomes = file_optouts(
        _profile(), db, approved_only=True,
        playbooks_dir=PLAYBOOKS_DIR / "mugshots",
        assist=lambda info: "skipped",
    )
    assert outcomes[0]["method"] == "skipped"
    assert db.find_listing("mugshots.com", "https://mugshots.com/x")["status"] == "approved"


def test_mailto_encodes_newlines():
    link = build_mailto("a@b.com", "Hi there", "line1\nline2")
    assert "line1%0D%0Aline2" in link and "Hi%20there" in link


# -- review: Enter is safe, 'o' opens -------------------------------------------

def test_review_enter_defers_and_open_reprompts(db, monkeypatch):
    opened = []
    monkeypatch.setattr("privacyworm.browser.open_in_default_browser", lambda u: opened.append(u) or True)
    db.add_listing(broker="spokeo", listing_url="https://spokeo.com/x/1", confidence="high", match_score=90)
    db.add_listing(broker="spokeo", listing_url="https://spokeo.com/x/2", confidence="low", match_score=10)
    sys.stdin = io.StringIO("o\ny\n\n")
    try:
        summary = review_listings(_profile(), db)
    finally:
        sys.stdin = sys.__stdin__
    assert opened == ["https://spokeo.com/x/1"]
    assert summary == {"approved": 1, "rejected": 0, "skipped": 1, "no_playbook": 0}
    assert db.find_listing("spokeo", "https://spokeo.com/x/2")["status"] == "needs_review"


# -- reminder timing ---------------------------------------------------------------

def test_reminder_only_when_due_and_not_nagging(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIVACYWORM_CONFIG_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    desktop.set_next_due((now + timedelta(days=5)).isoformat())
    assert not desktop.should_remind(now)
    desktop.set_next_due((now - timedelta(days=1)).isoformat())
    assert desktop.should_remind(now)
    data = desktop.read_schedule()
    data["last_reminded"] = now.isoformat()
    desktop.write_schedule(data)
    assert not desktop.should_remind(now + timedelta(days=1))
    assert desktop.should_remind(now + timedelta(days=desktop.RENAG_DAYS))
