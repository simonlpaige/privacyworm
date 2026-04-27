"""Tests for SQLite state management."""

import tempfile
from pathlib import Path

import pytest

from privacyworm.state import StateDB


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    state = StateDB(db_path=path)
    yield state
    state.close()
    path.unlink(missing_ok=True)


def test_add_and_get_listing(db: StateDB):
    lid = db.add_listing(
        broker="spokeo",
        listing_url="https://spokeo.com/Simon-Paige/123",
        confidence="medium",
        match_score=52,
        matched_fields=["full_name", "state"],
    )
    assert lid == 1
    listings = db.get_listings(broker="spokeo")
    assert len(listings) == 1
    assert listings[0]["confidence"] == "medium"
    assert listings[0]["match_score"] == 52
    assert listings[0]["status"] == "found"


def test_update_listing_status(db: StateDB):
    lid = db.add_listing(broker="spokeo")
    db.update_listing_status(lid, "opt_out_filed")
    listings = db.get_listings(status="opt_out_filed")
    assert len(listings) == 1


def test_invalid_listing_status(db: StateDB):
    lid = db.add_listing(broker="spokeo")
    with pytest.raises(ValueError):
        db.update_listing_status(lid, "bogus")


def test_optout_lifecycle(db: StateDB):
    lid = db.add_listing(broker="spokeo")
    oid = db.add_optout(lid, method="web_form", details="filed via form")
    assert oid == 1

    pending = db.get_optouts(status="pending")
    assert len(pending) == 1

    db.confirm_optout(oid)
    confirmed = db.get_optouts(status="confirmed")
    assert len(confirmed) == 1
    assert confirmed[0]["confirmation_received_at"] is not None


def test_optout_failure(db: StateDB):
    lid = db.add_listing(broker="spokeo")
    oid = db.add_optout(lid, method="email")
    db.fail_optout(oid, details="SMTP timeout")
    failed = db.get_optouts(status="failed")
    assert len(failed) == 1
    assert failed[0]["details"] == "SMTP timeout"


def test_summary(db: StateDB):
    lid1 = db.add_listing(broker="spokeo")
    lid2 = db.add_listing(broker="whitepages")
    db.add_optout(lid1, method="web_form")
    oid2 = db.add_optout(lid2, method="email")
    db.confirm_optout(oid2)

    s = db.summary()
    assert s["total_listings"] == 2
    assert s["pending_optouts"] == 1
    assert s["confirmed_optouts"] == 1


def test_duplicate_listing_ignored(db: StateDB):
    db.add_listing(broker="spokeo", listing_url="https://spokeo.com/John-Doe/123")
    db.add_listing(broker="spokeo", listing_url="https://spokeo.com/John-Doe/123")
    listings = db.get_listings(broker="spokeo")
    assert len(listings) == 1


def test_rescan_scheduling(db: StateDB):
    db.set_rescan("spokeo", "2026-07-22T00:00:00+00:00")
    due = db.get_due_rescans()
    assert len(due) == 0  # future date, not due yet

    db.set_rescan("whitepages", "2020-01-01T00:00:00+00:00")
    due = db.get_due_rescans()
    assert len(due) == 1
    assert due[0]["broker"] == "whitepages"
