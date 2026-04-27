"""Tests for the encrypted social-token store."""

import tempfile
from pathlib import Path

import pytest

from privacyworm.social import tokens


def _temp_path() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".enc", delete=False) as f:
        return Path(f.name)


def test_save_and_load_roundtrip():
    path = _temp_path()
    try:
        tokens.save_tokens(
            {"reddit": {"access_token": "abc", "refresh_token": "def"}},
            "test-pass",
            path,
        )
        loaded = tokens.load_tokens("test-pass", path)
        assert loaded["reddit"]["access_token"] == "abc"
        assert loaded["reddit"]["refresh_token"] == "def"
    finally:
        path.unlink(missing_ok=True)


def test_wrong_passphrase_fails():
    path = _temp_path()
    try:
        tokens.save_tokens({"twitter": {"access_token": "x"}}, "right-pass", path)
        with pytest.raises(Exception):
            tokens.load_tokens("wrong-pass", path)
    finally:
        path.unlink(missing_ok=True)


def test_missing_file_returns_empty():
    path = Path(tempfile.gettempdir()) / "privacyworm-nonexistent.enc"
    if path.exists():
        path.unlink()
    assert tokens.load_tokens("pass", path) == {}


def test_no_plaintext_on_disk():
    path = _temp_path()
    try:
        tokens.save_tokens(
            {"reddit": {"access_token": "supersecret-token-123"}},
            "test-pass",
            path,
        )
        raw = path.read_text()
        assert "supersecret-token-123" not in raw
    finally:
        path.unlink(missing_ok=True)
