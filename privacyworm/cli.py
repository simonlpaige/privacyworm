"""Click-based CLI for PrivacyWorm."""

import getpass
import logging
import sys
from pathlib import Path

import click
import yaml

from privacyworm import __version__
from privacyworm.cli_helpers import load_profile as _load_profile
from privacyworm.config import (
    SOCIAL_TOKENS_FILENAME,
    enable_state_encryption,
    get_config_dir,
    get_network_log_path,
    get_profile_path,
    get_raw_network_log_path,
    get_state_db_path,
    is_state_encryption_enabled,
    unencrypted_warning_marker,
)
from privacyworm.mugshot.cli import mugshot as _mugshot_group
from privacyworm.profile import (
    Address,
    InboxConfig,
    Name,
    Profile,
    decrypt_profile,
    encrypt_profile,
)
from privacyworm.extract import extract_listings_from_html
from privacyworm.playbook import load_all_playbooks
from privacyworm.runner import check_inbox, file_optouts, review_listings, scan_all
from privacyworm.social.cli import social as _social_group
from privacyworm.state import StateDB

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("privacyworm")


@click.group()
@click.version_option(__version__)
def cli():
    """PrivacyWorm - find your data-broker listings and opt out."""
    pass


def _warn_unencrypted_state_once() -> None:
    """Print the one-time warning when state.db is not encrypted.

    The warning only fires when the user has not already opted into
    encryption and has not already seen the warning. After the first
    time, a marker file in the config dir keeps us from nagging again.
    """
    if is_state_encryption_enabled():
        return
    marker = unencrypted_warning_marker()
    if marker.exists():
        return
    click.echo(
        "Note: state.db is unencrypted. It contains broker names and "
        "listing URLs - not your full PII, but enough that a snoop could "
        "tell which sites had your info. Run 'privacyworm init "
        "--encrypt-state' to encrypt it from now on.",
        err=True,
    )
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("warned\n", encoding="utf-8")
    except OSError:
        pass


def _open_state(passphrase: str | None = None) -> StateDB:
    """Open StateDB with the right encryption mode for this install."""
    if is_state_encryption_enabled():
        if passphrase is None:
            passphrase = getpass.getpass("Passphrase (for encrypted state.db): ")
        return StateDB(passphrase=passphrase)
    _warn_unencrypted_state_once()
    return StateDB()


def _load_profile_and_state() -> tuple[Profile, StateDB, str | None]:
    """Decrypt the profile and open StateDB with the same passphrase."""
    if is_state_encryption_enabled():
        passphrase = getpass.getpass("Passphrase: ")
        profile = _load_profile(passphrase)
        db = StateDB(passphrase=passphrase)
        return profile, db, passphrase
    profile = _load_profile()
    db = _open_state()
    return profile, db, None


@cli.command()
@click.option(
    "--encrypt-state",
    is_flag=True,
    help="Also encrypt the local state database with the same passphrase.",
)
def init(encrypt_state):
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

    if encrypt_state:
        enable_state_encryption()
        click.echo(
            "State database will be encrypted (state.db.enc) using the same "
            "passphrase. Each command will prompt you for it."
        )
        # If a plaintext state.db is already on disk from a previous run,
        # encrypt it now so we don't leave it lying around.
        plaintext_db = get_state_db_path(encrypted=False)
        encrypted_db = get_state_db_path(encrypted=True)
        if plaintext_db.exists() and not encrypted_db.exists():
            db = StateDB(passphrase=passphrase)
            db.close()
            click.echo("Existing state.db migrated to state.db.enc.")

    click.echo("You're all set. Run 'privacyworm scan' to see what the brokers have on you.")


DROP_REMINDER = (
    "You're in California. The state's DROP system (drop.oag.ca.gov)\n"
    "lets you send one deletion request to 500+ registered brokers. It\n"
    "started accepting requests on January 1, 2026 and the brokers must\n"
    "process them by August 1, 2026. PrivacyWorm handles the brokers\n"
    "outside that system and keeps evidence per request. Consider\n"
    "running DROP first.\n"
    "Pass --skip-drop-reminder to silence this."
)


def _maybe_drop_reminder(profile, skip: bool) -> None:
    """Print the DROP reminder once per command invocation when applicable."""
    if skip:
        return
    if not profile.addresses:
        return
    state = (profile.addresses[0].state or "").upper()
    if state == "CA":
        click.echo(DROP_REMINDER, err=True)
        click.echo("", err=True)


@cli.command()
@click.option("--broker", default=None, help="Scan a single broker by name.")
@click.option("--headed", is_flag=True, help="Open a visible browser window.")
@click.option(
    "--skip-drop-reminder",
    is_flag=True,
    help="Don't print the California DROP reminder.",
)
def scan(broker, headed, skip_drop_reminder):
    """Search data brokers for your listings."""
    profile, db, _ = _load_profile_and_state()
    _maybe_drop_reminder(profile, skip_drop_reminder)

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
        click.echo(
            "Run 'privacyworm review' to look at what was found and approve "
            "individual listings before any opt-out gets filed."
        )

    db.close()


@cli.command()
@click.option("--broker", default=None, help="Review listings from a single broker.")
def review(broker):
    """Walk found listings, show evidence, and approve them one by one.

    This is the safety step between scan and opt-out. PrivacyWorm shows
    the broker, the score, the matched fields, and the exact opt-out
    payload that would go out the door. You answer y / N / skip / quit.
    Only listings you approve here move on when you run
    'privacyworm optout --approved-only'.
    """
    profile, db, _ = _load_profile_and_state()
    summary = review_listings(profile, db, broker_name=broker)
    click.echo(
        "\nReview summary: "
        f"approved {summary['approved']}, "
        f"rejected {summary['rejected']}, "
        f"skipped {summary['skipped']}"
        + (f", no playbook {summary['no_playbook']}" if summary["no_playbook"] else "")
    )
    if summary["approved"]:
        click.echo(
            "Run 'privacyworm optout --approved-only' to file the approved "
            "opt-outs."
        )
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
@click.option(
    "--approved-only",
    is_flag=True,
    help="Only file opt-outs for listings already approved with 'privacyworm review'.",
)
@click.option(
    "--skip-drop-reminder",
    is_flag=True,
    help="Don't print the California DROP reminder.",
)
def optout(dry_run, headed, broker, auto_confirm, approved_only, skip_drop_reminder):
    """File opt-out requests for found listings."""
    click.echo(
        "By proceeding, you confirm these are opt-out requests for your own information.\n"
        "Do not use this tool to file requests on behalf of others without their consent.\n"
    )

    profile, db, _ = _load_profile_and_state()
    _maybe_drop_reminder(profile, skip_drop_reminder)

    if dry_run:
        click.echo("DRY RUN - nothing will actually be sent.\n")

    outcomes = file_optouts(
        profile,
        db,
        dry_run=dry_run,
        headed=headed,
        broker_name=broker,
        auto_confirm=auto_confirm,
        approved_only=approved_only,
    )

    if not outcomes:
        if approved_only:
            click.echo(
                "No approved listings yet. Run 'privacyworm review' first to "
                "approve individual listings."
            )
        else:
            click.echo("No listings to opt out from. Run 'privacyworm scan' first.")
    else:
        for o in outcomes:
            status = "OK" if o["success"] else "FAILED"
            click.echo(f"  [{status}] {o['broker']} (listing #{o['listing_id']}): {o['details']}")

    db.close()


@cli.command()
def status():
    """Show current status of listings, opt-outs, and confirmations."""
    db = _open_state()
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
    profile, db, _ = _load_profile_and_state()

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
@click.option(
    "--auto-confirm-inbox",
    is_flag=True,
    help=(
        "Skip the per-link y/N prompt for confirmation emails. HTML-only "
        "emails are still confirmed by the user even with this flag set."
    ),
)
def check(auto_confirm_inbox):
    """Poll IMAP inbox for confirmation emails and process them."""
    profile, db, _ = _load_profile_and_state()

    click.echo("Checking inbox for confirmation emails...\n")
    if auto_confirm_inbox:
        click.echo(
            "WARNING: --auto-confirm-inbox skips the per-link prompt. "
            "PrivacyWorm still validates that each link's domain and "
            "path match the broker's playbook, but you give up the last "
            "human look at the URL. Use it only when you trust the "
            "playbook's allowlists for that broker.",
            err=True,
        )
    processed = check_inbox(profile, db, auto_confirm_inbox=auto_confirm_inbox)

    if not processed:
        click.echo("No new confirmations found.")
    else:
        for p in processed:
            click.echo(f"  Confirmed: {p['broker']} (optout #{p['optout_id']})")

    db.close()


@cli.command()
def registries():
    """List the official state data-broker registries.

    These are state-run systems where data brokers must register and
    where consumers can sometimes file mass deletion requests. They are
    not run by PrivacyWorm; the tool just points you at them.
    """
    entries = [
        ("California (DROP)",
         "drop.oag.ca.gov",
         "One request reaches 500+ brokers registered with the state. "
         "Live since 2026-01-01; brokers must process by 2026-08-01."),
        ("Texas",
         "sos.state.tx.us (search 'data broker registration')",
         "Texas Secretary of State data broker registry."),
        ("Oregon",
         "justice.oregon.gov/databrokers",
         "Oregon Data Broker Registry, run by the state DOJ."),
        ("Vermont",
         "sec.state.vt.us/businesses/data-brokers",
         "Vermont's data broker registry, the first US registry."),
    ]
    click.echo("Official state data-broker registries:\n")
    for name, url, blurb in entries:
        click.echo(f"  {name}")
        click.echo(f"    {url}")
        click.echo(f"    {blurb}\n")
    click.echo(
        "PrivacyWorm covers brokers outside these registries and keeps\n"
        "per-request evidence. Use the registry first when you're eligible."
    )


@cli.command(name="purge-state")
@click.option(
    "--yes",
    "confirmed",
    is_flag=True,
    help="Skip the interactive confirmation prompt.",
)
def purge_state(confirmed):
    """Delete state.db (or state.db.enc), wiping local listing history.

    This is destructive. Listings, opt-out records, and the rescan
    schedule all go away. Your profile and tokens stay where they are.
    """
    plaintext = get_state_db_path(encrypted=False)
    encrypted = get_state_db_path(encrypted=True)
    targets = [p for p in (plaintext, encrypted) if p.exists()]
    if not targets:
        click.echo("No state database found - nothing to do.")
        return
    click.echo("This will delete:")
    for t in targets:
        click.echo(f"  - {t}")
    if not confirmed:
        if not click.confirm("Delete these files?", default=False):
            click.echo("Aborted.")
            return
    for t in targets:
        try:
            t.unlink()
            click.echo(f"Deleted {t}")
        except OSError as e:
            click.echo(f"Could not delete {t}: {e}", err=True)


@cli.command(name="delete-profile")
@click.option(
    "--yes",
    "confirmed",
    is_flag=True,
    help="Skip the interactive confirmation prompt.",
)
def delete_profile(confirmed):
    """Delete the encrypted profile and any social tokens.

    Big-deal command. Without the profile file, the tool has nothing to
    scan with. The encrypted file is overwritten with random bytes
    before unlinking so a forensic recovery is at least harder.
    """
    profile_path = get_profile_path(encrypted=True)
    tokens_path = get_config_dir() / SOCIAL_TOKENS_FILENAME
    targets = [p for p in (profile_path, tokens_path) if p.exists()]
    if not targets:
        click.echo("No profile or token files found - nothing to do.")
        return
    click.echo("WARNING: This deletes your profile and social tokens.")
    click.echo("After this you will need to run 'privacyworm init' from scratch.")
    click.echo("Files to remove:")
    for t in targets:
        click.echo(f"  - {t}")
    if not confirmed:
        if not click.confirm("Are you sure?", default=False):
            click.echo("Aborted.")
            return
    import os as _os
    for t in targets:
        try:
            size = t.stat().st_size
            with open(t, "r+b") as f:
                f.write(_os.urandom(size))
                f.flush()
            t.unlink()
            click.echo(f"Deleted {t}")
        except OSError as e:
            click.echo(f"Could not delete {t}: {e}", err=True)


@cli.command(name="test-playbooks")
@click.option("--broker", default=None, help="Test a single broker by name.")
def test_playbooks(broker):
    """Run each playbook's tests.fixtures section against its expectations.

    For every playbook with a ``tests.fixtures`` block, load each HTML
    fixture, run the extract selectors against it, and compare the
    output against the ``expected`` dict in the playbook. This is a
    fast round-trip you can run before sending a PR.
    """
    repo_root = Path(__file__).resolve().parent.parent
    playbooks = load_all_playbooks()
    if broker:
        playbooks = [pb for pb in playbooks if pb.broker == broker]
        if not playbooks:
            click.echo(f"No playbook found for broker: {broker}")
            raise SystemExit(1)

    total = 0
    failed = 0
    for pb in playbooks:
        if not pb.tests or not pb.tests.fixtures:
            continue
        for fx in pb.tests.fixtures:
            total += 1
            fixture_path = (repo_root / fx.file).resolve()
            if not fixture_path.exists():
                click.echo(f"  [FAIL] {pb.broker}: fixture {fx.file} not found")
                failed += 1
                continue
            html = fixture_path.read_text(encoding="utf-8")
            try:
                listings = extract_listings_from_html(
                    html,
                    pb.search.listing_selectors,
                    pb.extract,
                )
            except Exception as e:
                click.echo(f"  [FAIL] {pb.broker}: extract error: {e}")
                failed += 1
                continue

            problems = []
            if fx.expected:
                if fx.expected.listings is not None and len(listings) != fx.expected.listings:
                    problems.append(
                        f"expected {fx.expected.listings} listings, got {len(listings)}"
                    )
                if fx.expected.first_listing and listings:
                    first = listings[0]
                    for key, expected_val in fx.expected.first_listing.items():
                        actual = first.get(key)
                        if actual != expected_val:
                            problems.append(
                                f"first_listing.{key}: expected {expected_val!r}, got {actual!r}"
                            )
            if problems:
                click.echo(f"  [FAIL] {pb.broker}: {'; '.join(problems)}")
                failed += 1
            else:
                click.echo(f"  [OK]   {pb.broker}: {len(listings)} listing(s) extracted")

    if total == 0:
        click.echo("No playbook fixtures to run.")
    else:
        click.echo(f"\n{total - failed}/{total} playbook fixture(s) passed.")
    if failed:
        raise SystemExit(1)


@cli.command(name="export-audit")
@click.option(
    "--include-sensitive",
    is_flag=True,
    help="Print the raw, unredacted log instead of the audit-safe version.",
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write to this file instead of stdout.",
)
def export_audit(include_sensitive, out):
    """Print the network audit log.

    The default reads ~/.privacyworm/network.log, which has names and
    query strings redacted and is safe to share. Pass --include-sensitive
    to read the raw log at ~/.privacyworm/network.raw.log, which only
    exists when PRIVACYWORM_KEEP_RAW_LOG=1 was set during the runs.
    """
    if include_sensitive:
        path = get_raw_network_log_path()
        if not path.exists():
            click.echo(
                "No raw log found. Set PRIVACYWORM_KEEP_RAW_LOG=1 before running "
                "scan or optout to keep an unredacted log."
            )
            raise SystemExit(1)
    else:
        path = get_network_log_path()
        if not path.exists():
            click.echo("No audit log yet. Run a scan or opt-out first.")
            raise SystemExit(1)

    text = path.read_text(encoding="utf-8", errors="replace")
    if out:
        Path(out).write_text(text, encoding="utf-8")
        click.echo(f"Wrote {len(text)} bytes to {out}")
    else:
        click.echo(text, nl=False)


cli.add_command(_social_group)
cli.add_command(_mugshot_group)


if __name__ == "__main__":
    cli()
