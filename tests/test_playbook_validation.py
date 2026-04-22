"""Tests for playbook loading and validation."""

from pathlib import Path

import pytest

from privacyworm.playbook import Playbook, load_playbook, load_all_playbooks

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_valid_playbook():
    pb = load_playbook(FIXTURES / "valid_playbook.yaml")
    assert pb.broker == "testbroker"
    assert pb.display_name == "Test Broker"
    assert pb.search.method == "browser"
    assert pb.opt_out.method == "web_form"
    assert pb.opt_out.requires_confirmation is True
    assert pb.rescan_days == 90


def test_load_invalid_search_method():
    with pytest.raises(Exception):
        load_playbook(FIXTURES / "invalid_playbook.yaml")


def test_playbook_rejects_bad_opt_out_method():
    with pytest.raises(Exception):
        Playbook(
            broker="x",
            display_name="X",
            homepage="https://x.com",
            last_updated="2026-01-01",
            search={"url_template": "https://x.com/{first}", "method": "browser"},
            opt_out={"method": "smoke_signal"},
        )


def test_playbook_rejects_bad_confirmation_type():
    with pytest.raises(Exception):
        Playbook(
            broker="x",
            display_name="X",
            homepage="https://x.com",
            last_updated="2026-01-01",
            search={"url_template": "https://x.com/{first}", "method": "browser"},
            opt_out={"method": "web_form", "confirmation_type": "telepathy"},
        )


def test_playbook_defaults():
    pb = Playbook(
        broker="x",
        display_name="X",
        homepage="https://x.com",
        last_updated="2026-01-01",
        search={"url_template": "https://x.com/{first}", "method": "browser"},
        opt_out={"method": "manual"},
    )
    assert pb.rescan_days == 90
    assert pb.opt_out.confirmation_type == "none"
    assert pb.maintainer == "@community"


def test_load_all_real_playbooks():
    """All shipped playbooks must parse without error."""
    playbooks_dir = Path(__file__).parent.parent / "playbooks"
    if not playbooks_dir.exists():
        pytest.skip("playbooks directory not yet created")
    playbooks = load_all_playbooks(playbooks_dir)
    assert len(playbooks) >= 1
    for pb in playbooks:
        assert pb.broker
        assert pb.display_name
        assert pb.opt_out.method in {"web_form", "email", "manual"}
