"""Orchestrator: scan -> match -> opt-out -> log."""

import logging
from datetime import datetime, timedelta, timezone

import tldextract

from privacyworm.brokers.base import BaseBroker
from privacyworm.brokers.email import EmailBroker
from privacyworm.brokers.web_form import WebFormBroker
from privacyworm.inbox.imap import ImapInbox
from privacyworm.playbook import Playbook, load_all_playbooks, get_playbook
from privacyworm.profile import Profile
from privacyworm.state import StateDB

logger = logging.getLogger("privacyworm")


def _registered_domain(url: str) -> str:
    """Return the registered domain (e.g. 'spokeo.com') for a URL."""
    extracted = tldextract.extract(url)
    return f"{extracted.domain}.{extracted.suffix}" if extracted.suffix else extracted.domain


def _same_registered_domain(url_a: str, url_b: str) -> bool:
    return _registered_domain(url_a) == _registered_domain(url_b)


def _make_broker(playbook: Playbook, profile: Profile, headed: bool = False) -> BaseBroker:
    """Pick the right broker class based on opt-out method."""
    if playbook.opt_out.method == "email":
        return EmailBroker(playbook, profile, headed)
    # web_form and manual both use the web form broker for scanning
    return WebFormBroker(playbook, profile, headed)


def scan_broker(
    playbook: Playbook,
    profile: Profile,
    db: StateDB,
    headed: bool = False,
) -> list[dict]:
    """Scan a single broker and store any new listings found."""
    broker = _make_broker(playbook, profile, headed)
    listings = broker.scan()

    for listing in listings:
        db.add_listing(
            broker=playbook.broker,
            listing_url=listing.get("listing_url"),
            matched_name=listing.get("matched_name"),
            matched_city=listing.get("matched_city"),
            matched_state=listing.get("matched_state"),
            raw_snippet=listing.get("raw_snippet"),
        )

    # Update rescan schedule
    next_scan = datetime.now(timezone.utc) + timedelta(days=playbook.rescan_days)
    db.set_rescan(playbook.broker, next_scan.isoformat())

    return listings


def scan_all(
    profile: Profile,
    db: StateDB,
    headed: bool = False,
    broker_name: str | None = None,
) -> dict[str, list[dict]]:
    """Scan all brokers (or one specific broker) and return results."""
    results: dict[str, list[dict]] = {}

    if broker_name:
        playbook = get_playbook(broker_name)
        if not playbook:
            logger.error(f"No playbook found for broker: {broker_name}")
            return results
        results[broker_name] = scan_broker(playbook, profile, db, headed)
    else:
        for playbook in load_all_playbooks():
            try:
                results[playbook.broker] = scan_broker(playbook, profile, db, headed)
            except Exception as e:
                logger.error(f"Error scanning {playbook.broker}: {e}")
                results[playbook.broker] = []

    return results


def _confirm_listing(listing_row: dict) -> bool:
    """Show the listing to the user and ask whether to file an opt-out.

    Returns True when the user types y/yes (case-insensitive), else False.
    """
    print()
    print(f"  Broker:   {listing_row['broker']}")
    if listing_row.get("matched_name"):
        print(f"  Name:     {listing_row['matched_name']}")
    location_parts = [p for p in (listing_row.get("matched_city"), listing_row.get("matched_state")) if p]
    if location_parts:
        print(f"  Location: {', '.join(location_parts)}")
    if listing_row.get("listing_url"):
        print(f"  URL:      {listing_row['listing_url']}")
    snippet = listing_row.get("raw_snippet")
    if snippet:
        print(f"  Snippet:  {snippet}")
    try:
        answer = input("File opt-out for this listing? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def file_optouts(
    profile: Profile,
    db: StateDB,
    dry_run: bool = False,
    headed: bool = False,
    broker_name: str | None = None,
    auto_confirm: bool = False,
) -> list[dict]:
    """File opt-out requests for all found listings.

    Unless ``auto_confirm`` is True, each listing is shown to the user and
    they must type ``y`` / ``yes`` before the request is filed.
    """
    listings = db.get_listings(broker=broker_name, status="found")
    outcomes = []

    for listing_row in listings:
        playbook = get_playbook(listing_row["broker"])
        if not playbook:
            logger.warning(f"No playbook for broker {listing_row['broker']}, skipping")
            continue

        if not auto_confirm and not _confirm_listing(listing_row):
            outcomes.append({
                "broker": listing_row["broker"],
                "listing_id": listing_row["id"],
                "success": False,
                "method": "skipped",
                "details": "Skipped by user.",
            })
            continue

        if playbook.opt_out.method == "manual":
            msg = playbook.opt_out.manual_instructions or "Manual opt-out required. See playbook for instructions."
            outcomes.append({
                "broker": listing_row["broker"],
                "listing_id": listing_row["id"],
                "success": False,
                "method": "manual",
                "details": msg,
            })
            continue

        broker = _make_broker(playbook, profile, headed)
        result = broker.file_optout(listing_row, dry_run=dry_run)

        if not dry_run and result["success"]:
            db.update_listing_status(listing_row["id"], "opt_out_filed")
            db.add_optout(
                listing_id=listing_row["id"],
                method=result["method"],
                details=result["details"],
            )

        outcomes.append({
            "broker": listing_row["broker"],
            "listing_id": listing_row["id"],
            **result,
        })

    return outcomes


def check_inbox(profile: Profile, db: StateDB) -> list[dict]:
    """Check the inbox for confirmation emails and process them."""
    if not profile.inbox:
        logger.warning("No inbox configured in profile. Run 'privacyworm init' to set one up.")
        return []

    inbox = ImapInbox(profile.inbox)
    processed = []

    # Get all pending opt-outs and their associated playbooks
    pending = db.get_optouts(status="pending")
    for optout in pending:
        listing = db.get_listings(status="opt_out_filed")
        matching_listing = next((l for l in listing if l["id"] == optout["listing_id"]), None)
        if not matching_listing:
            continue

        playbook = get_playbook(matching_listing["broker"])
        if not playbook or not playbook.opt_out.requires_confirmation:
            continue

        subject_filter = playbook.opt_out.confirmation_subject_contains
        if not subject_filter:
            continue

        confirmations = inbox.check_confirmations(subject_filter)
        for conf in confirmations:
            # Try to click the confirmation link
            for link in conf["links"]:
                if not _same_registered_domain(link, playbook.homepage):
                    logger.warning(
                        "Skipping confirmation link: domain does not match broker homepage "
                        f"(link={link!r}, homepage={playbook.homepage!r})"
                    )
                    continue
                if inbox.click_confirmation_link(link):
                    db.confirm_optout(optout["id"])
                    db.update_listing_status(matching_listing["id"], "opt_out_confirmed")
                    processed.append({
                        "broker": matching_listing["broker"],
                        "optout_id": optout["id"],
                        "link": link,
                    })
                    break

    return processed
