"""Click-based CLI for PrivacyWorm."""

import getpass
import logging
import sys

import click
import yaml

from privacyworm import __version__
from privacyworm.config import get_config_dir, get_profile_path
from privacyworm.profile import (
    Address,
    InboxConfig,
    Name,
    Profile,
    decrypt_profile,
    encrypt_profile,
)
from privacyworm.runner import check_inbox, file_optouts, scan_all
from privacyworm.state import StateDB

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("privacyworm")


def _load_profile() -> Profile:
    """Prompt for passphrase and decrypt the profile."""
    path = get_profile_path(encrypted=True)
    if not path.exists():
        click.echo("No profile found. Run 'privacyworm init' first.")
        raise SystemExit(1)
    passphrase = getpass.getpass("Passphrase: ")
    try:
        return decrypt_profile(passphrase, path)
    except Exception:
        click.echo("Wrong passphrase or corrupted profile.")
        raise SystemExit(1)


@click.group()
@click.version_option(__version__)
def cli():
    """PrivacyWorm - find your data-broker listings and opt out."""
    pass


@cli.command()
def init():
    """Set up your profile (interactive, encrypted on disk)."""
    click.echo("Let's set up your profile. This info stays on your machine, encrypted.\n")

    first = click.prompt("First name")
    last = click.prompt("Last name")
    middle = click.prompt("Middle name/initial (blank to skip)", default="", show_default=False)

    name = Name(first=first, last=last, middle=middle or None)

    aliases = []
    click.echo("\nAliases (other names brokers might list you under). Blank line to stop.")
    while True:
        alias = click.prompt("Alias", default="", show_default=False)
        if not alias:
            break
        aliases.append(alias)

    addresses = []
    click.echo("\nAddresses (current and past). Blank street to stop.")
    while True:
        street = click.prompt("Street address", default="", show_default=False)
        if not street:
            break
        city = click.prompt("City")
        state = click.prompt("State (2-letter)")
        zip_code = click.prompt("ZIP")
        addresses.append(Address(street=street, city=city, state=state, zip=zip_code))

    dob = click.prompt("\nDate of birth (YYYY-MM-DD, blank to skip)", default="", show_default=False)

    phones = []
    click.echo("\nPhone numbers. Blank to stop.")
    while True:
        phone = click.prompt("Phone", default="", show_default=False)
        if not phone:
            break
        phones.append(phone)

    emails = []
    click.echo("\nEmail addresses. Blank to stop.")
    while True:
        em = click.prompt("Email", default="", show_default=False)
        if not em:
            break
        emails.append(em)

    relatives = []
    click.echo("\nRelatives (helps avoid false positives). Blank to stop.")
    while True:
        rel = click.prompt("Relative name", default="", show_default=False)
        if not rel:
            break
        relatives.append(rel)

    inbox = None
    if click.confirm("\nSet up email inbox for confirmation tracking?", default=False):
        host = click.prompt("IMAP host", default="imap.gmail.com")
        port = click.prompt("IMAP port", default=993, type=int)
        user = click.prompt("IMAP username (email)")
        pass_env = click.prompt("Env var name for IMAP password", default="PRIVACYWORM_INBOX_PASS")
        inbox = InboxConfig(host=host, port=port, user=user, pass_env=pass_env)

    profile = Profile(
        name=name,
        aliases=aliases,
        addresses=addresses,
        dob=dob or None,
        phones=phones,
        emails=emails,
        relatives=relatives,
        inbox=inbox,
    )

    click.echo("")
    passphrase = getpass.getpass("Choose a passphrase to encrypt your profile: ")
    confirm = getpass.getpass("Confirm passphrase: ")
    if passphrase != confirm:
        click.echo("Passphrases don't match. Try again.")
        raise SystemExit(1)

    path = get_profile_path(encrypted=True)
    encrypt_profile(profile, passphrase, path)
    click.echo(f"\nProfile encrypted and saved to {path}")
    click.echo("You're all set. Run 'privacyworm scan' to see what the brokers have on you.")


@cli.command()
@click.option("--broker", default=None, help="Scan a single broker by name.")
@click.option("--headed", is_flag=True, help="Open a visible browser window.")
def scan(broker, headed):
    """Search data brokers for your listings."""
    profile = _load_profile()
    db = StateDB()

    click.echo(f"Scanning {'all brokers' if not broker else broker}...\n")
    results = scan_all(profile, db, headed=headed, broker_name=broker)

    total = 0
    for broker_name, listings in results.items():
        count = len(listings)
        total += count
        if count:
            click.echo(f"  {broker_name}: {count} listing(s) found")
        else:
            click.echo(f"  {broker_name}: clean")

    click.echo(f"\nTotal: {total} listing(s) found across {len(results)} broker(s).")
    if total > 0:
        click.echo("Run 'privacyworm optout --dry-run' to preview opt-out requests.")

    db.close()


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would be sent without actually sending.")
@click.option("--headed", is_flag=True, help="Open a visible browser window.")
@click.option("--broker", default=None, help="Opt out from a single broker.")
@click.option(
    "--yes",
    "--auto-confirm",
    "auto_confirm",
    is_flag=True,
    help="Skip the per-listing confirmation prompt and file every opt-out.",
)
def optout(dry_run, headed, broker, auto_confirm):
    """File opt-out requests for found listings."""
    click.echo(
        "By proceeding, you confirm these are opt-out requests for your own information.\n"
        "Do not use this tool to file requests on behalf of others without their consent.\n"
    )

    profile = _load_profile()
    db = StateDB()

    if dry_run:
        click.echo("DRY RUN - nothing will actually be sent.\n")

    outcomes = file_optouts(
        profile,
        db,
        dry_run=dry_run,
        headed=headed,
        broker_name=broker,
        auto_confirm=auto_confirm,
    )

    if not outcomes:
        click.echo("No listings to opt out from. Run 'privacyworm scan' first.")
    else:
        for o in outcomes:
            status = "OK" if o["success"] else "FAILED"
            click.echo(f"  [{status}] {o['broker']} (listing #{o['listing_id']}): {o['details']}")

    db.close()


@cli.command()
def status():
    """Show current status of listings, opt-outs, and confirmations."""
    db = StateDB()
    s = db.summary()

    click.echo("PrivacyWorm Status")
    click.echo("------------------")
    click.echo(f"  Listings found:      {s['total_listings']}")
    click.echo(f"  Opt-outs pending:    {s['pending_optouts']}")
    click.echo(f"  Opt-outs confirmed:  {s['confirmed_optouts']}")

    # Show per-broker breakdown
    listings = db.get_listings()
    brokers = {}
    for l in listings:
        b = l["broker"]
        brokers.setdefault(b, {"found": 0, "opted_out": 0})
        if l["status"] == "found":
            brokers[b]["found"] += 1
        elif l["status"] in ("opt_out_filed", "opt_out_confirmed"):
            brokers[b]["opted_out"] += 1

    if brokers:
        click.echo("\n  Per broker:")
        for b, counts in sorted(brokers.items()):
            click.echo(f"    {b}: {counts['found']} found, {counts['opted_out']} opted out")

    db.close()


@cli.command()
@click.option("--headed", is_flag=True, help="Open a visible browser window.")
def rescan(headed):
    """Re-check brokers that are due for a rescan."""
    profile = _load_profile()
    db = StateDB()

    due = db.get_due_rescans()
    if not due:
        click.echo("No brokers are due for a rescan yet.")
        db.close()
        return

    click.echo(f"Re-scanning {len(due)} broker(s) that are due...\n")
    for r in due:
        results = scan_all(profile, db, headed=headed, broker_name=r["broker"])
        count = sum(len(v) for v in results.values())
        click.echo(f"  {r['broker']}: {count} listing(s) found")

    db.close()


@cli.group()
def inbox():
    """Manage confirmation email tracking."""
    pass


@inbox.command()
def check():
    """Poll IMAP inbox for confirmation emails and process them."""
    profile = _load_profile()
    db = StateDB()

    click.echo("Checking inbox for confirmation emails...\n")
    processed = check_inbox(profile, db)

    if not processed:
        click.echo("No new confirmations found.")
    else:
        for p in processed:
            click.echo(f"  Confirmed: {p['broker']} (optout #{p['optout_id']})")

    db.close()


if __name__ == "__main__":
    cli()
