"""Click commands for ``privacyworm mugshot ...``.

Three jobs:

1. ``scan``    - search known mugshot sites for the user's name.
2. ``optout``  - file removal requests via web form / email / manual.
3. ``letters`` - generate a GDPR Art. 17 / CCPA right-to-delete PDF.

Mugshot playbooks live in ``playbooks/mugshots/`` and use exactly the
same YAML schema as the data-broker playbooks. The scan/optout flow
delegates to the existing runner with a custom ``playbooks_dir``.
"""

import logging
from pathlib import Path

import click

from privacyworm.cli_helpers import load_profile
from privacyworm.playbook import get_playbook, load_all_playbooks
from privacyworm.runner import file_optouts, scan_all
from privacyworm.state import StateDB

logger = logging.getLogger("privacyworm")

MUGSHOT_PLAYBOOKS_DIR = (
    Path(__file__).parent.parent.parent / "playbooks" / "mugshots"
)


@click.group(name="mugshot")
def mugshot():
    """Find and remove mugshot listings."""


@mugshot.command()
@click.option("--site", default=None, help="Limit to one mugshot site.")
@click.option("--headed", is_flag=True, help="Open a visible browser window.")
def scan(site, headed):
    """Search known mugshot sites for your name."""
    profile = load_profile()
    db = StateDB()
    click.echo(f"Scanning {'all mugshot sites' if not site else site}...\n")
    results = scan_all(
        profile,
        db,
        headed=headed,
        broker_name=site,
        playbooks_dir=MUGSHOT_PLAYBOOKS_DIR,
    )
    total = 0
    for name, listings in results.items():
        n = len(listings)
        total += n
        if n:
            click.echo(f"  {name}: {n} listing(s) found")
        else:
            click.echo(f"  {name}: clean")
    click.echo(f"\nTotal: {total} mugshot listing(s) across {len(results)} site(s).")
    if total > 0:
        click.echo("Run 'privacyworm mugshot optout --dry-run' to preview.")
    db.close()


@mugshot.command()
@click.option("--site", default=None, help="Limit to one mugshot site.")
@click.option("--headed", is_flag=True, help="Open a visible browser window.")
@click.option("--dry-run", is_flag=True, help="Show what would be sent, send nothing.")
@click.option(
    "--yes",
    "--auto-confirm",
    "auto_confirm",
    is_flag=True,
    help="Skip the per-listing confirmation prompt and file every removal.",
)
def optout(site, headed, dry_run, auto_confirm):
    """File removal requests for found mugshot listings."""
    click.echo(
        "By proceeding, you confirm these are removal requests for your own information.\n"
        "Do not use this tool to file requests on behalf of others without their consent.\n"
    )
    profile = load_profile()
    db = StateDB()
    if dry_run:
        click.echo("DRY RUN - nothing will actually be sent.\n")
    outcomes = file_optouts(
        profile,
        db,
        dry_run=dry_run,
        headed=headed,
        broker_name=site,
        playbooks_dir=MUGSHOT_PLAYBOOKS_DIR,
        auto_confirm=auto_confirm,
    )
    if not outcomes:
        click.echo("No listings to opt out from. Run 'privacyworm mugshot scan' first.")
    else:
        for o in outcomes:
            status = "OK" if o["success"] else "FAILED"
            click.echo(
                f"  [{status}] {o['broker']} listing #{o['listing_id']}: {o['details']}"
            )
    db.close()


@mugshot.command()
@click.option("--site", required=True, help="Mugshot site to address the letter to.")
@click.option(
    "--law",
    type=click.Choice(["gdpr", "ccpa"]),
    default="ccpa",
    show_default=True,
    help="Which legal basis to cite.",
)
@click.option(
    "--out",
    default=None,
    help="Output PDF path. Defaults to <site>-<law>-letter.pdf in the current folder.",
)
def letters(site, law, out):
    """Generate a removal demand letter PDF."""
    profile = load_profile()
    pb = get_playbook(site, directory=MUGSHOT_PLAYBOOKS_DIR)
    if not pb:
        click.echo(f"No mugshot playbook for '{site}'. Available sites:")
        for p in load_all_playbooks(directory=MUGSHOT_PLAYBOOKS_DIR):
            click.echo(f"  - {p.broker} ({p.display_name})")
        return
    out_path = Path(out) if out else Path.cwd() / f"{site}-{law}-letter.pdf"
    try:
        from privacyworm.mugshot.letters import render_letter
    except ImportError as exc:
        click.echo(
            "PDF generation needs reportlab. Install the extra:\n"
            "  pip install 'privacyworm[mugshot]'"
        )
        raise SystemExit(1) from exc
    render_letter(profile, pb, law, out_path)
    click.echo(f"Wrote {out_path}")
