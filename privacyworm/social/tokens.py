"""Encrypted store for social platform OAuth tokens.

Reuses the same Fernet + PBKDF2-HMAC-SHA256 (480k iterations) scheme used
in ``profile.py``. Tokens live in ``~/.privacyworm/social_tokens.yaml.enc``.
"""

import base64
import json
import os
from pathlib import Path

import yaml
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from privacyworm.config import get_config_dir

TOKENS_FILENAME = "social_tokens.yaml.enc"


def get_tokens_path() -> Path:
    """Return the path to the encrypted social tokens file."""
    return get_config_dir() / TOKENS_FILENAME


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def save_tokens(tokens: dict, passphrase: str, path: Path | None = None) -> None:
    """Encrypt a ``{platform: token_dict}`` mapping and write to disk."""
    if path is None:
        path = get_tokens_path()
    salt = os.urandom(16)
    key = _derive_key(passphrase, salt)
    fernet = Fernet(key)
    plaintext = yaml.dump(tokens, default_flow_style=False).encode()
    encrypted = fernet.encrypt(plaintext)
    payload = {
        "salt": base64.b64encode(salt).decode(),
        "data": encrypted.decode(),
    }
    path.write_text(json.dumps(payload))


def load_tokens(passphrase: str, path: Path | None = None) -> dict:
    """Read and decrypt the tokens file. Returns ``{}`` if the file is missing."""
    if path is None:
        path = get_tokens_path()
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    salt = base64.b64decode(payload["salt"])
    key = _derive_key(passphrase, salt)
    fernet = Fernet(key)
    plaintext = fernet.decrypt(payload["data"].encode())
    return yaml.safe_load(plaintext) or {}
