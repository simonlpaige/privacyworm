"""Optional: remember the passphrase in the operating system's keychain.

Autopilot runs while you're away, so it can't ask for your passphrase.
If you turn it on, the passphrase is stored in Windows Credential
Manager / macOS Keychain / the Linux Secret Service - the same place your
browser keeps saved passwords - and only your user account can read it.
Turning autopilot off removes it.
"""

from __future__ import annotations

SERVICE = "privacyworm"
ACCOUNT = "profile-passphrase"


def _keyring():
    try:
        import keyring

        return keyring
    except Exception:  # noqa: BLE001 - missing or broken backend
        return None


def available() -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        backend = kr.get_keyring()
    except Exception:  # noqa: BLE001
        return False
    name = type(backend).__name__.lower()
    return "fail" not in name and "null" not in name


def save(passphrase: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.set_password(SERVICE, ACCOUNT, passphrase)
        return True
    except Exception:  # noqa: BLE001
        return False


def load() -> str | None:
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(SERVICE, ACCOUNT)
    except Exception:  # noqa: BLE001
        return None


def forget() -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, ACCOUNT)
    except Exception:  # noqa: BLE001
        pass
