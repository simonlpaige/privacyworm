"""Click-based CLI for PrivacyWorm."""

import getpass
import logging
import sys
from pathlib import Path

import click

from privacyworm import __version__, desktop, ui
from privacyworm.cli_helpers import unlock_profile
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
from privacyworm.extract import extract_listings_from_html
from privacyworm.mugshot.cli import mugshot as _mugshot_group
from privacyworm.playbook import load_all_playbooks
from privacyworm.profile import (
    Profile,
    encrypt_profile,
)
from privacyworm.runner import check_inbox, file_optouts, review_listings, scan_all
from privacyworm.social.cli import social as _social_group
from privacyworm.state import StateDB

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("privacyworm")


@click.group(invoke_without_command=True)
@click.version_option(__version__)
@click.option("--reminder", is_flag=True, hidden=True, help="Opened by the daily reminder.")
@click.pass_context
def cli(ctx, reminder):
    """PrivacyWorm - find your data-broker listings and opt out.

    Run it with no command for the guided mode (recommended). The
    commands below are for scripting and power users.
    """
    if ctx.invoked_subcommand is None:
        from privacyworm.wizard import run

        run(reminder=reminder)


def main() -> None:
    """Console entry point."""
    if sys.platform == "win32":
        try:
            import colorama

            colorama.just_fix_windows_console()
        except ImportError:
            pass
    # Never crash on a console that can't print the odd ✓ (old Windows
    # code pages, output redirected to a file).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr,attr-defined,unused-ignore]
        except (AttributeError, ValueError):
            pass
    cli()


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
    profile, passphrase = unlock_profile()
    if is_state_encryption_enabled():
        return profile, StateDB(passphrase=passphrase), passphrase
    return profile, _open_state(), passphrase


@cli.command()
@click.option(
    "--encrypt-state",
    is_flag=True,
    help="Also encrypt the local state database with the same passphrase.",
)
def init(encrypt_state):
    """Set up your profile (interactive, encrypted on disk)."""
    from privacyworm.profile_setup import ask_new_passphrase, interview

    path = get_profile_path(encrypted=True)
    if path.exists() and not click.confirm(
        "You already have a profile. Replace it with a new one?", default=False
    ):
        click.echo("Kept your existing profile. To change it, run 'privacyworm' and choose 'Edit my info'.")
        return
    click.echo("Let's set up your profile. This info stays on your machine, encrypted.")
    profile = interview()
    click.echo("")
    passphrase = ask_new_passphrase()

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

    click.echo("You're all set. Run 'privacyworm' for a guided check-up, or 'privacyworm scan'.")


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
@click.option(
    "--assist/--no-assist",
    default=None,
    help=(
        "Open each form in a visible window pre-filled and let you click Submit "
        "(default when run in a terminal), or submit automatically."
    ),
)
def optout(dry_run, headed, broker, auto_confirm, approved_only, skip_drop_reminder, assist):
    """File opt-out requests for found listings."""
    click.echo(
        "By proceeding, you confirm these are opt-out requests for your own information.\n"
        "Do not use this tool to file requests on behalf of others without their consent.\n"
    )

    profile, db, _ = _load_profile_and_state()
    _maybe_drop_reminder(profile, skip_drop_reminder)

    if dry_run:
        click.echo("DRY RUN - nothing will actually be sent.\n")

    if assist is None:
        assist = ui.interactive() and not auto_confirm and not dry_run
    outcomes = file_optouts(
        profile,
        db,
        dry_run=dry_run,
        headed=headed,
        broker_name=broker,
        auto_confirm=auto_confirm,
        approved_only=approved_only,
        assist=_assist_callback() if assist else None,
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


def _assist_callback():
    from privacyworm.wizard import _assist

    return _assist


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
    for row in listings:
        b = row["broker"]
        brokers.setdefault(b, {"found": 0, "opted_out": 0})
        if row["status"] == "found":
            brokers[b]["found"] += 1
        elif row["status"] in ("opt_out_filed", "opt_out_confirmed", "optout_submitted"):
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


def print_registries() -> None:
    """Print the official state data-broker registries."""
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


@cli.command()
def registries():
    """List the official state data-broker registries.

    These are state-run systems where data brokers must register and
    where consumers can sometimes file mass deletion requests. They are
    not run by PrivacyWorm; the tool just points you at them.
    """
    print_registries()


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


INSTALL_SH = "https://raw.githubusercontent.com/simonlpaige/privacyworm/main/install.sh"
INSTALL_PS1 = "https://raw.githubusercontent.com/simonlpaige/privacyworm/main/install.ps1"


def _install_command() -> str:
    if desktop.platform() == "windows":
        return f'powershell -ExecutionPolicy Bypass -c "irm {INSTALL_PS1} | iex"'
    return f"curl -fsSL {INSTALL_SH} | sh"


@cli.command()
def checkup():
    """Guided check-up: search, review, and remove - all in one go."""
    from privacyworm.wizard import Session
    from privacyworm.wizard import checkup as run_checkup

    logging.getLogger("privacyworm").setLevel(logging.WARNING)
    profile, db, passphrase = _load_profile_and_state()
    session = Session(profile, passphrase or "", db)
    try:
        run_checkup(session)
    finally:
        session.close()


@cli.command()
@click.option("--no-shortcut", is_flag=True, help="Don't add PrivacyWorm to the app menu.")
@click.option("--no-browser", is_flag=True, help="Skip the browser check/download.")
def setup(no_shortcut, no_browser):
    """Finish installing: check the browser and add an app-menu shortcut.

    The installers run this for you. It's safe to run again any time.
    """
    from privacyworm.browser import ensure_browser

    ok = True
    if not no_browser:
        ok = ensure_browser(echo=lambda m: click.echo(f"  {m}"))
    if not no_shortcut:
        try:
            msg = desktop.create_shortcut()
            if msg:
                click.echo(f"  {msg}")
        except OSError as e:
            click.echo(f"  Couldn't add a shortcut ({e}). You can still type 'privacyworm'.")
    if not ok:
        raise SystemExit(1)


@cli.command()
def doctor():
    """Check that everything PrivacyWorm needs is working."""
    from privacyworm.browser import ensure_browser

    click.echo(f"PrivacyWorm {__version__} on Python {sys.version.split()[0]} ({desktop.platform()})")
    pbs = load_all_playbooks()
    click.echo(f"  Broker playbooks: {len(pbs)} loaded")
    if not pbs:
        click.echo("  ! No playbooks found - reinstall with: " + _install_command())
    profile = get_profile_path(encrypted=True)
    click.echo(f"  Profile: {'set up' if profile.exists() else 'not set up yet (run privacyworm)'}")
    click.echo(f"  Data folder: {get_config_dir()}")
    click.echo(f"  Reminders: {'on' if desktop.reminders_enabled() else 'off'}")
    if not ensure_browser(echo=lambda m: click.echo(f"  {m}")):
        raise SystemExit(1)
    click.echo("All good.")


@cli.command()
@click.argument("action", required=False, type=click.Choice(["on", "off", "status"]))
def reminders(action):
    """Turn check-up reminders on or off (privacyworm reminders on|off)."""
    if action == "on":
        ok, msg = desktop.enable_reminders()
        click.echo(msg)
        if not ok:
            raise SystemExit(1)
    elif action == "off":
        _, msg = desktop.disable_reminders()
        click.echo(msg)
    else:
        on = desktop.reminders_enabled()
        due = desktop.next_due()
        click.echo(f"Reminders are {'on' if on else 'off'}.")
        if due:
            click.echo(f"Next check-up due: {due.astimezone().strftime('%b %d, %Y').replace(' 0', ' ')}")
        if not on:
            click.echo("Turn them on with: privacyworm reminders on")


@cli.command(hidden=True)
@click.option("--force", is_flag=True, help="Remind even if nothing is due.")
def remind(force):
    """Run by the OS scheduler. Opens PrivacyWorm when a check-up is due."""
    click.echo(desktop.remind(force=force))


@cli.command()
def update():
    """How to update PrivacyWorm to the latest version."""
    click.echo("Run the installer again - it updates in place and keeps your data:")
    click.echo(f"  {_install_command()}")


@cli.command()
@click.option("--keep-data", is_flag=True, help="Keep your encrypted profile and history.")
def uninstall(keep_data):
    """Remove reminders, shortcuts and (optionally) your data, then the app."""
    click.echo("This removes PrivacyWorm's reminders and app-menu shortcut.")
    if not keep_data:
        click.echo(f"It also deletes your saved info and history in {get_config_dir()}.")
    if not click.confirm("Go ahead?", default=False):
        click.echo("Nothing changed.")
        return
    desktop.disable_reminders()
    desktop.remove_shortcut()
    if not keep_data:
        import os as _os
        import shutil as _shutil

        p = get_profile_path(encrypted=True)
        if p.exists():
            p.write_bytes(_os.urandom(p.stat().st_size))
        _shutil.rmtree(get_config_dir(), ignore_errors=True)
    click.echo("Done. To remove the program itself, run:")
    click.echo("  uv tool uninstall privacyworm")
    click.echo("(or 'pip uninstall privacyworm' if you installed it with pip)")


cli.add_command(_social_group)
cli.add_command(_mugshot_group)


if __name__ == "__main__":
    main()
