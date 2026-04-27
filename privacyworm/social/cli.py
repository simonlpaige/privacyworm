"""Click commands for ``privacyworm social ...``.

Three jobs:

1. Scan your old posts and comments on Reddit and Twitter/X.
2. Delete or overwrite them in bulk by age.
3. Walk you through closing your account on any of the major platforms.

OAuth tokens are encrypted at rest with the same scheme as the profile
file. The CLI prompts for the same passphrase you set during
``privacyworm init`` so there is only one secret to remember.
"""

import getpass
import logging
from datetime import datetime, timezone

import click

from privacyworm.social import oauth, tokens
from privacyworm.social import reddit as reddit_api
from privacyworm.social import twitter as twitter_api
from privacyworm.social.playbook import load_all_social_playbooks, load_social_playbook
from privacyworm.social.timeparse import parse_iso_date, parse_period

logger = logging.getLogger("privacyworm")

API_PLATFORMS = {"reddit", "twitter"}


def _passphrase(prompt: str = "Passphrase: ") -> str:
    return getpass.getpass(prompt)


def _get_token(platform: str, passphrase: str) -> dict:
    """Look up a saved token, or run the OAuth login flow if there is none."""
    saved = tokens.load_tokens(passphrase)
    tok = saved.get(platform)
    if tok:
        return tok
    click.echo(f"No saved token for {platform}. Starting login in your browser...")
    tok = oauth.run_pkce_flow(platform)
    saved[platform] = tok
    tokens.save_tokens(saved, passphrase)
    click.echo(f"Saved {platform} token to ~/.privacyworm/social_tokens.yaml.enc")
    return tok


def _resolve_cutoff(older_than: str | None, before: str | None) -> datetime:
    if older_than and before:
        raise click.UsageError("Pass --older-than or --before, not both.")
    if not older_than and not before:
        raise click.UsageError("Provide --older-than (e.g. 1y) or --before (YYYY-MM-DD).")
    if older_than:
        try:
            return datetime.now(timezone.utc) - parse_period(older_than)
        except ValueError as e:
            raise click.BadParameter(str(e), param_hint="--older-than")
    try:
        return parse_iso_date(before)  # type: ignore[arg-type]
    except ValueError:
        raise click.BadParameter("Use YYYY-MM-DD format.", param_hint="--before")


@click.group(name="social")
def social():
    """Scan, edit, and remove your social-media history; close accounts."""


@social.command()
@click.option("--platform", default=None, help="Limit to one platform.")
def scan(platform):
    """Find your old posts and comments.

    Counts only; nothing is changed. Use ``social delete`` or
    ``social overwrite`` to actually remove anything.
    """
    targets = [platform] if platform else sorted(API_PLATFORMS)
    pw = _passphrase()
    for plat in targets:
        click.echo(f"\nScanning {plat}...")
        if plat not in API_PLATFORMS:
            click.echo(
                f"  {plat}: not supported for automated scan. "
                f"Try `privacyworm social delete-account --platform {plat}`."
            )
            continue
        try:
            tok = _get_token(plat, pw)
            if plat == "reddit":
                username = reddit_api.get_username(tok)
                comments = reddit_api.list_user_content(tok, "comments", username)
                posts = reddit_api.list_user_content(tok, "submitted", username)
                click.echo(
                    f"  reddit (u/{username}): "
                    f"{len(comments)} comments, {len(posts)} posts"
                )
            elif plat == "twitter":
                uid = twitter_api.get_user_id(tok)
                tw = twitter_api.list_tweets(tok, uid)
                click.echo(f"  twitter (id {uid}): {len(tw)} tweets")
        except Exception as e:
            click.echo(f"  {plat} error: {e}")


@social.command()
@click.option("--platform", required=True, help="reddit or twitter.")
@click.option("--older-than", default=None, help="e.g. 1y, 30d, 6m, 2w")
@click.option("--before", default=None, help="YYYY-MM-DD")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted, do nothing.")
def delete(platform, older_than, before, dry_run):
    """Delete posts/comments older than a cutoff.

    On Reddit, deletes both comments and self-posts. On Twitter/X,
    deletes tweets via the v2 API.
    """
    if platform not in API_PLATFORMS:
        click.echo(
            f"Automated delete is only available for {sorted(API_PLATFORMS)}. "
            f"Use `privacyworm social delete-account --platform {platform}` "
            f"for the manual walkthrough."
        )
        return

    cutoff = _resolve_cutoff(older_than, before)
    click.echo(f"Cutoff: items older than {cutoff.isoformat()}")
    if dry_run:
        click.echo("DRY RUN - nothing will actually be deleted.\n")

    pw = _passphrase()
    tok = _get_token(platform, pw)
    deleted = 0
    failed = 0

    if platform == "reddit":
        username = reddit_api.get_username(tok)
        targets: list[tuple[str, datetime, str]] = []
        for kind in ("comments", "submitted"):
            for it in reddit_api.list_user_content(tok, kind, username):
                created = datetime.fromtimestamp(it["created_utc"], tz=timezone.utc)
                if created < cutoff:
                    snippet = it.get("body") or it.get("title") or ""
                    targets.append((it["name"], created, snippet))
        click.echo(f"Found {len(targets)} reddit item(s) to delete.")
        for fullname, when, snippet in targets:
            preview = snippet[:60].replace("\n", " ")
            if dry_run:
                click.echo(f"  DRY RUN delete {fullname} ({when.date()}): {preview}")
                continue
            ok = reddit_api.delete_thing(tok, fullname)
            if ok:
                deleted += 1
            else:
                failed += 1
            click.echo(
                f"  [{'OK' if ok else 'FAIL'}] delete {fullname} "
                f"({when.date()}): {preview}"
            )
    else:  # twitter
        uid = twitter_api.get_user_id(tok)
        tweets = twitter_api.list_tweets(tok, uid)
        targets_tw = []
        for t in tweets:
            created_at = t.get("created_at")
            if not created_at:
                continue
            when = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if when < cutoff:
                targets_tw.append(t)
        click.echo(f"Found {len(targets_tw)} tweet(s) to delete.")
        for t in targets_tw:
            preview = t.get("text", "")[:60].replace("\n", " ")
            if dry_run:
                click.echo(f"  DRY RUN delete {t['id']}: {preview}")
                continue
            ok = twitter_api.delete_tweet(tok, t["id"])
            if ok:
                deleted += 1
            else:
                failed += 1
            click.echo(f"  [{'OK' if ok else 'FAIL'}] delete {t['id']}: {preview}")

    if not dry_run:
        click.echo(f"\nDone. Deleted {deleted}, failed {failed}.")


@social.command()
@click.option("--platform", required=True, help="reddit (twitter has no edit endpoint).")
@click.option("--older-than", default=None, help="e.g. 1y, 6m")
@click.option("--before", default=None, help="YYYY-MM-DD")
@click.option(
    "--text",
    default=".",
    help="Replacement text. Default is a single period, which is the smallest "
    "edit Reddit accepts.",
)
@click.option("--dry-run", is_flag=True)
def overwrite(platform, older_than, before, text, dry_run):
    """Overwrite the text of old comments before deletion.

    Why bother? Deleted comments can sometimes be recovered from
    third-party Reddit archives. Editing the text first means the
    archive snapshot of the new (empty-ish) version is what survives.
    Run ``social delete`` afterwards to actually remove the items.
    """
    if platform != "reddit":
        click.echo(
            "Overwrite is only supported on Reddit. Twitter/X has no public "
            "tweet-edit endpoint, so deletion is the only option there."
        )
        return

    cutoff = _resolve_cutoff(older_than, before)
    click.echo(f"Cutoff: comments older than {cutoff.isoformat()}")
    if dry_run:
        click.echo("DRY RUN - nothing will actually be overwritten.\n")

    pw = _passphrase()
    tok = _get_token(platform, pw)
    username = reddit_api.get_username(tok)

    edited = 0
    skipped = 0
    for it in reddit_api.list_user_content(tok, "comments", username):
        created = datetime.fromtimestamp(it["created_utc"], tz=timezone.utc)
        if created >= cutoff:
            continue
        if dry_run:
            click.echo(f"  DRY RUN overwrite {it['name']} -> {text!r}")
            continue
        if reddit_api.edit_thing(tok, it["name"], text):
            edited += 1
        else:
            skipped += 1

    if not dry_run:
        click.echo(
            f"\nOverwrote {edited} comments (skipped {skipped}). "
            f"They are still on Reddit until you also run `social delete`."
        )


@social.command(name="delete-account")
@click.option("--platform", required=True, help="The platform whose account you want to close.")
def delete_account(platform):
    """Walk through closing an account on a platform.

    Each platform has a YAML playbook in ``playbooks/social/`` describing
    the deletion URL, the steps, and how long it takes for the platform
    to actually purge your data.
    """
    pb = load_social_playbook(platform)
    if not pb:
        click.echo(f"No playbook for '{platform}'. Available platforms:")
        for p in load_all_social_playbooks():
            click.echo(f"  - {p.platform} ({p.display_name})")
        return

    click.echo(f"\n{pb.display_name} ({pb.homepage})")
    click.echo("-" * 60)
    if pb.api_method:
        click.echo(f"API method: {pb.api_method}")
    if pb.manual_url:
        click.echo(f"Manual deletion page: {pb.manual_url}")
    click.echo(f"Estimated time to complete: ~{pb.estimated_days_to_complete} day(s)")
    click.echo("\nSteps:")
    for i, step in enumerate(pb.instructions, 1):
        click.echo(f"  {i}. {step}")
    if pb.notes:
        click.echo(f"\nNote: {pb.notes}")
