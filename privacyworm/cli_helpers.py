"""Shared helpers for CLI commands."""

import getpass

import click

from privacyworm.config import get_profile_path, is_state_encryption_enabled
from privacyworm.profile import Profile, decrypt_profile
from privacyworm.state import StateDB


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


def unlock_profile(attempts: int = 3) -> tuple[Profile, str]:
    """Ask for the passphrase (up to ``attempts`` tries) and decrypt the profile.

    Returns (profile, passphrase) so the caller can reuse the passphrase
    for the encrypted state database without asking again.
    """
    path = get_profile_path(encrypted=True)
    if not path.exists():
        click.echo("No profile found. Run 'privacyworm' to set one up.")
        raise SystemExit(1)
    for attempt in range(1, attempts + 1):
        try:
            passphrase = getpass.getpass("  Passphrase: ")
        except EOFError:
            raise SystemExit(1) from None
        try:
            return decrypt_profile(passphrase, path), passphrase
        except Exception:  # noqa: BLE001 - wrong passphrase or damaged file
            left = attempts - attempt
            if left:
                click.echo(f"  That passphrase didn't work. {left} more {'try' if left == 1 else 'tries'}.")
    click.echo(
        "  Still no luck. If you've forgotten it, choose 'Start over' from the menu\n"
        "  or run 'privacyworm delete-profile' and set up again - your listings\n"
        "  will be found again on the next check-up."
    )
    raise SystemExit(1)


def open_state(passphrase: str | None) -> StateDB:
    """Open the state DB in whichever mode this install uses."""
    if is_state_encryption_enabled():
        if passphrase is None:
            passphrase = getpass.getpass("  Passphrase: ")
        return StateDB(passphrase=passphrase)
    return StateDB()


def load_profile_and_state() -> tuple[Profile, StateDB, str]:
    """Unlock the profile once and open state with the same passphrase."""
    profile, passphrase = unlock_profile()
    return profile, open_state(passphrase), passphrase
