"""Shared helpers for CLI commands."""

import getpass

import click

from privacyworm.config import get_profile_path
from privacyworm.profile import Profile, decrypt_profile


def load_profile(passphrase: str | None = None) -> Profile:
    """Prompt for the passphrase and decrypt the user's profile.

    If ``passphrase`` is given (e.g. from a tested caller), skip the prompt.
    Exits the process with code 1 if the profile is missing or the
    passphrase is wrong.
    """
    path = get_profile_path(encrypted=True)
    if not path.exists():
        click.echo("No profile found. Run 'privacyworm init' first.")
        raise SystemExit(1)
    if passphrase is None:
        passphrase = getpass.getpass("Passphrase: ")
    try:
        return decrypt_profile(passphrase, path)
    except Exception as exc:
        click.echo("Wrong passphrase or corrupted profile.")
        raise SystemExit(1) from exc
