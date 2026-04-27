"""Tests for the per-state legal_basis selection."""

from privacyworm.playbook import Playbook, resolve_legal_basis


def _make_pb(legal_basis):
    return Playbook(
        broker="x",
        display_name="X",
        homepage="https://x.com",
        last_updated="2026-04-27",
        search={"url_template": "https://x.com/{first}", "method": "browser"},
        opt_out={"method": "manual"},
        legal_basis=legal_basis,
    )


def test_returns_state_specific_when_present():
    pb = _make_pb({
        "default": "Voluntary opt-out",
        "CA": "California Delete Act / CCPA",
    })
    assert resolve_legal_basis(pb, "CA") == "California Delete Act / CCPA"


def test_state_lookup_is_case_insensitive():
    pb = _make_pb({"default": "Voluntary", "CA": "CCPA"})
    assert resolve_legal_basis(pb, "ca") == "CCPA"


def test_falls_back_to_default():
    pb = _make_pb({"default": "Voluntary", "CA": "CCPA"})
    assert resolve_legal_basis(pb, "NY") == "Voluntary"


def test_string_legal_basis_returned_as_is():
    pb = _make_pb("Plain string basis")
    assert resolve_legal_basis(pb, "CA") == "Plain string basis"


def test_no_basis_returns_none():
    pb = _make_pb(None)
    assert resolve_legal_basis(pb, "CA") is None
