"""Encrypted store for social platform OAuth tokens.

Reuses the same Fernet + Argon2id key derivation used in ``profile.py``,
through the shared ``encrypt_bytes`` / ``decrypt_bytes`` helpers. Tokens
live in ``~/.privacyworm/social_tokens.yaml.enc``.
"""

from pathlib import Path

import yaml

from privacyworm.config import get_config_dir
from privacyworm.profile import decrypt_bytes, encrypt_bytes

TOKENS_FILENAME = "social_tokens.yaml.enc"


def get_tokens_path() -> Path:
    """Return the path to the encrypted social tokens file."""
    return get_config_dir() / TOKENS_FILENAME


def save_tokens(tokens: dict, passphrase: str, path: Path | None = None) -> None:
    """Encrypt a ``{platform: token_dict}`` mapping and write to disk."""
    if path is None:
        path = get_tokens_path()
    plaintext = yaml.dump(tokens, default_flow_style=False).encode()
    path.write_bytes(encrypt_bytes(plaintext, passphrase))


def load_tokens(passphrase: str, path: Path | None = None) -> dict:
    """Read and decrypt the tokens file. Returns ``{}`` if the file is missing."""
    if path is None:
        path = get_tokens_path()
    if not path.exists():
        return {}
    plaintext = decrypt_bytes(path.read_bytes(), passphrase)
    return yaml.safe_load(plaintext) or {}
