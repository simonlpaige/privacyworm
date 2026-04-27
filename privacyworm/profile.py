"""User profile schema and encryption for PII stored at rest.

The profile is encrypted with Fernet, which is AES-128-CBC with an
HMAC-SHA256 tag. The key for Fernet is derived from the user's
passphrase with Argon2id, so a stolen profile.yaml.enc still demands a
serious amount of work per passphrase guess.
"""

import base64
import json
import os
from pathlib import Path
from typing import Optional

import yaml
from argon2.low_level import Type, hash_secret_raw
from cryptography.fernet import Fernet
from pydantic import BaseModel

KDF_KIND = "argon2id"
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST = 65_536  # 64 MiB
ARGON2_PARALLELISM = 4
ARGON2_HASH_LEN = 32


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


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a Fernet key from a passphrase using Argon2id.

    Fernet expects a urlsafe-base64 encoding of a 32-byte key. Argon2id
    gives us the raw bytes; we encode them to fit the Fernet API.
    """
    raw = hash_secret_raw(
        secret=passphrase.encode(),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LEN,
        type=Type.ID,
    )
    return base64.urlsafe_b64encode(raw)


def encrypt_bytes(plaintext: bytes, passphrase: str) -> bytes:
    """Encrypt raw bytes with the user's passphrase, return a JSON envelope.

    The envelope records which KDF was used so a future change to the
    derivation parameters can still read older blobs.
    """
    salt = os.urandom(16)
    key = derive_key(passphrase, salt)
    fernet = Fernet(key)
    encrypted = fernet.encrypt(plaintext)
    payload = {
        "kdf": KDF_KIND,
        "salt": base64.b64encode(salt).decode(),
        "data": encrypted.decode(),
    }
    return json.dumps(payload).encode()


def decrypt_bytes(blob: bytes, passphrase: str) -> bytes:
    """Decrypt a JSON envelope produced by encrypt_bytes."""
    payload = json.loads(blob.decode() if isinstance(blob, bytes) else blob)
    salt = base64.b64decode(payload["salt"])
    key = derive_key(passphrase, salt)
    fernet = Fernet(key)
    return fernet.decrypt(payload["data"].encode())


def encrypt_profile(profile: Profile, passphrase: str, path: Path) -> None:
    """Encrypt and write a profile to disk."""
    plaintext = yaml.dump(profile.model_dump(), default_flow_style=False).encode()
    path.write_bytes(encrypt_bytes(plaintext, passphrase))


def decrypt_profile(passphrase: str, path: Path) -> Profile:
    """Read and decrypt a profile from disk."""
    plaintext = decrypt_bytes(path.read_bytes(), passphrase)
    data = yaml.safe_load(plaintext)
    return Profile(**data)
