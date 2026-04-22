"""User profile schema and encryption for PII stored at rest."""

import base64
import json
import os
from pathlib import Path
from typing import Optional

import yaml
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from pydantic import BaseModel


class Name(BaseModel):
    first: str
    last: str
    middle: Optional[str] = None


class Address(BaseModel):
    street: str
    city: str
    state: str
    zip: str
    from_year: Optional[int] = None
    to_year: Optional[int] = None


class InboxConfig(BaseModel):
    type: str = "imap"
    host: str = "imap.gmail.com"
    port: int = 993
    user: str = ""
    pass_env: str = "PRIVACYWORM_INBOX_PASS"


class Profile(BaseModel):
    name: Name
    aliases: list[str] = []
    addresses: list[Address] = []
    dob: Optional[str] = None
    phones: list[str] = []
    emails: list[str] = []
    relatives: list[str] = []
    inbox: Optional[InboxConfig] = None


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a Fernet key from a passphrase using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def encrypt_profile(profile: Profile, passphrase: str, path: Path) -> None:
    """Encrypt and write a profile to disk."""
    salt = os.urandom(16)
    key = _derive_key(passphrase, salt)
    fernet = Fernet(key)
    plaintext = yaml.dump(profile.model_dump(), default_flow_style=False).encode()
    encrypted = fernet.encrypt(plaintext)
    payload = {
        "salt": base64.b64encode(salt).decode(),
        "data": encrypted.decode(),
    }
    path.write_text(json.dumps(payload))


def decrypt_profile(passphrase: str, path: Path) -> Profile:
    """Read and decrypt a profile from disk."""
    payload = json.loads(path.read_text())
    salt = base64.b64decode(payload["salt"])
    key = _derive_key(passphrase, salt)
    fernet = Fernet(key)
    plaintext = fernet.decrypt(payload["data"].encode())
    data = yaml.safe_load(plaintext)
    return Profile(**data)
