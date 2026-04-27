"""Tests for the optional state.db encryption mode."""

import os
import tempfile
from pathlib import Path

import pytest

from privacyworm.state import StateDB


def _isolated_config(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("PRIVACYWORM_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_encrypted_state_round_trip(tmp_path, monkeypatch):
    """Adding listings and reopening encrypted state should give them back."""
    cfg = _isolated_config(tmp_path, monkeypatch)
    passphrase = "test-passphrase-please-no-touchy"

    db = StateDB(passphrase=passphrase, encrypted=True)
    db.add_listing(broker="spokeo", listing_url="https://spokeo.com/x/1")
    db.add_listing(broker="spokeo", listing_url="https://spokeo.com/x/2")
    db.close()

    # On disk we expect state.db.enc, not state.db.
    assert (cfg / "state.db.enc").exists()
    assert not (cfg / "state.db").exists()

    db2 = StateDB(passphrase=passphrase, encrypted=True)
    listings = db2.get_listings(broker="spokeo")
    db2.close()

    assert len(listings) == 2
    assert {l["listing_url"] for l in listings} == {
        "https://spokeo.com/x/1",
        "https://spokeo.com/x/2",
    }


def test_encrypted_state_rejects_wrong_passphrase(tmp_path, monkeypatch):
    _isolated_config(tmp_path, monkeypatch)
    db = StateDB(passphrase="correct", encrypted=True)
    db.add_listing(broker="spokeo")
    db.close()

    with pytest.raises(Exception):
        StateDB(passphrase="wrong", encrypted=True)


def test_encrypted_state_requires_passphrase(tmp_path, monkeypatch):
    _isolated_config(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        StateDB(encrypted=True)


def test_plaintext_state_default_path_works(tmp_path, monkeypatch):
    cfg = _isolated_config(tmp_path, monkeypatch)
    db = StateDB()
    db.add_listing(broker="spokeo")
    db.close()
    assert (cfg / "state.db").exists()
    assert not (cfg / "state.db.enc").exists()
