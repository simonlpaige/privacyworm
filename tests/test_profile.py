"""Tests for profile schema and encryption."""

import tempfile
from pathlib import Path

from privacyworm.profile import Profile, encrypt_profile, decrypt_profile


def _make_profile() -> Profile:
    return Profile(
        name={"first": "Simon", "last": "Paige", "middle": "L"},
        aliases=["Simon L Paige"],
        addresses=[{
            "street": "123 Example St",
            "city": "Kansas City",
            "state": "MO",
            "zip": "64113",
        }],
        dob="1985-06-15",
        phones=["+1-816-555-0123"],
        emails=["simon@example.com"],
        relatives=["Jane Paige"],
    )


def test_profile_validates():
    p = _make_profile()
    assert p.name.first == "Simon"
    assert p.name.last == "Paige"
    assert len(p.addresses) == 1
    assert p.addresses[0].city == "Kansas City"


def test_profile_minimal():
    p = Profile(name={"first": "Test", "last": "User"})
    assert p.aliases == []
    assert p.phones == []


def test_encrypt_decrypt_roundtrip():
    profile = _make_profile()
    passphrase = "test-passphrase-not-real"
    with tempfile.NamedTemporaryFile(suffix=".enc", delete=False) as f:
        path = Path(f.name)
    try:
        encrypt_profile(profile, passphrase, path)
        assert path.exists()
        # The file should not contain plaintext PII
        raw = path.read_text()
        assert "Simon" not in raw
        assert "Kansas City" not in raw

        decrypted = decrypt_profile(passphrase, path)
        assert decrypted.name.first == "Simon"
        assert decrypted.name.last == "Paige"
        assert decrypted.addresses[0].city == "Kansas City"
        assert decrypted.emails == ["simon@example.com"]
    finally:
        path.unlink(missing_ok=True)


def test_decrypt_wrong_passphrase():
    profile = _make_profile()
    with tempfile.NamedTemporaryFile(suffix=".enc", delete=False) as f:
        path = Path(f.name)
    try:
        encrypt_profile(profile, "correct-pass", path)
        try:
            decrypt_profile("wrong-pass", path)
            assert False, "Should have raised an exception"
        except Exception:
            pass  # Expected - wrong passphrase
    finally:
        path.unlink(missing_ok=True)
