"""Tests for mugshot site playbooks (uses the broker schema)."""

from pathlib import Path

from privacyworm.playbook import load_all_playbooks, load_playbook

MUGSHOT_DIR = Path(__file__).parent.parent / "playbooks" / "mugshots"

EXPECTED_SITES = {
    "mugshots.com",
    "bustedmugshots.com",
    "arrestfacts.com",
    "justmugshots.com",
    "jailbase.com",
    "arrests.org",
    "instantcheckmate.com",
    "publicrecords.directory",
    "arrests.com",
    "mugshotsandmore.com",
}


def test_all_ten_mugshot_sites_have_playbooks():
    pbs = {p.broker for p in load_all_playbooks(MUGSHOT_DIR)}
    assert EXPECTED_SITES.issubset(pbs), f"Missing: {EXPECTED_SITES - pbs}"


def test_each_mugshot_playbook_validates():
    for f in MUGSHOT_DIR.glob("*.yaml"):
        pb = load_playbook(f)
        assert pb.broker
        assert pb.display_name
        assert pb.homepage.startswith("https://")
        assert pb.opt_out.method in {"web_form", "email", "manual"}


def test_mugshot_playbooks_isolated_from_main_playbook_dir():
    """Top-level scan must not pick up mugshot playbooks (they live in a subdir)."""
    main_dir = Path(__file__).parent.parent / "playbooks"
    main_brokers = {p.broker for p in load_all_playbooks(main_dir)}
    assert main_brokers.isdisjoint(EXPECTED_SITES)
