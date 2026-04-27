"""Tests for the social-platform deletion playbooks."""

from pathlib import Path

import pytest

from privacyworm.social.playbook import (
    SocialPlaybook,
    load_all_social_playbooks,
    load_social_playbook,
)

EXPECTED_PLATFORMS = {
    "reddit",
    "twitter",
    "facebook",
    "instagram",
    "tiktok",
    "linkedin",
    "pinterest",
    "tumblr",
    "mastodon",
}


def test_all_expected_platforms_have_a_playbook():
    pbs = {p.platform for p in load_all_social_playbooks()}
    assert EXPECTED_PLATFORMS.issubset(pbs), f"Missing: {EXPECTED_PLATFORMS - pbs}"


def test_load_one_playbook():
    pb = load_social_playbook("reddit")
    assert pb is not None
    assert pb.platform == "reddit"
    assert pb.display_name
    assert pb.homepage.startswith("https://")
    assert pb.estimated_days_to_complete > 0
    assert len(pb.instructions) >= 3


def test_load_unknown_platform_returns_none():
    assert load_social_playbook("myspace") is None


def test_playbook_validates_required_fields():
    with pytest.raises(Exception):
        SocialPlaybook(display_name="X", homepage="https://x.com")  # missing 'platform'


def test_estimated_days_default():
    pb = SocialPlaybook(platform="x", display_name="X", homepage="https://x.com")
    assert pb.estimated_days_to_complete == 30
