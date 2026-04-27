"""Tests for the review flow that gates opt-outs behind explicit approval."""

import io
import sys
import tempfile
from pathlib import Path

import pytest

from privacyworm.profile import Address, Name, Profile
from privacyworm.runner import file_optouts, review_listings
from privacyworm.state import StateDB


PLAYBOOKS = Path(__file__).parent.parent / "playbooks"


def _profile() -> Profile:
    return Profile(
        name=Name(first="Simon", last="Paige"),
        addresses=[Address(street="x", city="Kansas City", state="MO", zip="64113")],
        emails=["simon@example.com"],
    )


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    state = StateDB(db_path=path)
    yield state
    state.close()
    path.unlink(missing_ok=True)


def _drive_review(answers: list[str], profile, db):
    """Run review_listings with a fixed list of stdin answers."""
    sys.stdin = io.StringIO("\n".join(answers) + "\n")
    try:
        return review_listings(profile, db, playbooks_dir=PLAYBOOKS)
    finally:
        sys.stdin = sys.__stdin__


def test_review_marks_approved_and_rejected(db):
    profile = _profile()
    db.add_listing(broker="spokeo", listing_url="https://spokeo.com/x/1",
                   confidence="high", match_score=85, matched_fields=["full_name", "city"])
    db.add_listing(broker="spokeo", listing_url="https://spokeo.com/x/2",
                   confidence="medium", match_score=50, matched_fields=["full_name"])

    summary = _drive_review(["y", "n"], profile, db)
    assert summary["approved"] == 1
    assert summary["rejected"] == 1

    listings = db.get_listings(broker="spokeo")
    statuses = {l["listing_url"]: l["status"] for l in listings}
    assert statuses["https://spokeo.com/x/1"] == "approved"
    assert statuses["https://spokeo.com/x/2"] == "rejected"


def test_review_skip_keeps_listing_open(db):
    profile = _profile()
    db.add_listing(broker="spokeo", listing_url="https://spokeo.com/x/1",
                   confidence="medium", match_score=50, matched_fields=["full_name"])

    summary = _drive_review(["skip"], profile, db)
    assert summary["skipped"] == 1
    listings = db.get_listings(broker="spokeo")
    assert listings[0]["status"] == "needs_review"


def test_review_quit_stops_loop(db):
    profile = _profile()
    db.add_listing(broker="spokeo", listing_url="https://spokeo.com/x/1",
                   confidence="high", match_score=85, matched_fields=["full_name"])
    db.add_listing(broker="spokeo", listing_url="https://spokeo.com/x/2",
                   confidence="high", match_score=85, matched_fields=["full_name"])

    summary = _drive_review(["quit"], profile, db)
    assert summary["approved"] == 0
    assert summary["rejected"] == 0
    listings = sorted(db.get_listings(broker="spokeo"), key=lambda r: r["listing_url"])
    # Both should be marked needs_review (none auto-rejected by quit).
    assert all(l["status"] == "needs_review" for l in listings)


def test_optout_approved_only_skips_unreviewed(db):
    profile = _profile()
    db.add_listing(broker="spokeo", listing_url="https://spokeo.com/x/unreviewed",
                   confidence="high", match_score=85, matched_fields=["full_name"])
    # Pretend the user already approved this one.
    approved_id = db.add_listing(broker="spokeo", listing_url="https://spokeo.com/x/approved",
                                 confidence="high", match_score=85, matched_fields=["full_name"])
    db.update_listing_status(approved_id, "approved")

    outcomes = file_optouts(
        profile,
        db,
        dry_run=True,
        broker_name="spokeo",
        auto_confirm=True,
        approved_only=True,
        playbooks_dir=PLAYBOOKS,
    )
    # Only the approved listing should be processed.
    listing_ids = [o["listing_id"] for o in outcomes]
    assert listing_ids == [approved_id]
