"""Orchestrator: scan -> match -> opt-out -> log."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tldextract

from privacyworm.brokers.base import BaseBroker
from privacyworm.brokers.email import EmailBroker
from privacyworm.brokers.web_form import WebFormBroker
from privacyworm.inbox.imap import ImapInbox
from privacyworm.matching import score_listing
from privacyworm.playbook import Playbook, load_all_playbooks, get_playbook
from privacyworm.profile import Profile
from privacyworm.state import StateDB

ALL_MATCHABLE_FIELDS = ["full_name", "city", "state", "zip", "phone", "relative", "age"]

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
    """Scan a single broker, score each listing, and store the verdicts."""
    broker = _make_broker(playbook, profile, headed)
    listings = broker.scan()

    for listing in listings:
        text_for_scoring = " ".join(
            str(v) for v in (
                listing.get("matched_name"),
                listing.get("matched_city"),
                listing.get("matched_state"),
                listing.get("raw_snippet"),
            ) if v
        )
        verdict = score_listing(text_for_scoring, profile)
        listing["confidence"] = verdict["confidence"]
        listing["match_score"] = verdict["score"]
        listing["matched_fields"] = verdict["matched_fields"]

        db.add_listing(
            broker=playbook.broker,
            listing_url=listing.get("listing_url"),
            confidence=verdict["confidence"],
            match_score=verdict["score"],
            matched_fields=verdict["matched_fields"],
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
    playbooks_dir: Path | None = None,
) -> dict[str, list[dict]]:
    """Scan all brokers (or one specific broker) and return results.

    ``playbooks_dir`` lets callers point at a different folder of YAML
    playbooks (for example ``playbooks/mugshots/``) instead of the
    default broker collection.
    """
    results: dict[str, list[dict]] = {}

    if broker_name:
        playbook = get_playbook(broker_name, directory=playbooks_dir)
        if not playbook:
            logger.error(f"No playbook found for broker: {broker_name}")
            return results
        results[broker_name] = scan_broker(playbook, profile, db, headed)
    else:
        for playbook in load_all_playbooks(directory=playbooks_dir):
            try:
                results[playbook.broker] = scan_broker(playbook, profile, db, headed)
            except Exception as e:
                logger.error(f"Error scanning {playbook.broker}: {e}")
                results[playbook.broker] = []

    return results


def _confirm_listing(listing_row: dict, profile: Profile) -> bool:
    """Show the score and matched fields, then ask whether to file an opt-out.

    Returns True when the user types y/yes (case-insensitive), else False.
    """
    matched_fields_raw = listing_row.get("matched_fields") or "[]"
    try:
        matched_fields = json.loads(matched_fields_raw) if isinstance(matched_fields_raw, str) else list(matched_fields_raw)
    except (json.JSONDecodeError, TypeError):
        matched_fields = []
    missing_fields = [f for f in ALL_MATCHABLE_FIELDS if f not in matched_fields]

    score = listing_row.get("match_score")
    confidence = listing_row.get("confidence") or "unknown"

    name_str = f"{profile.name.first} {profile.name.last}".strip()
    location = ""
    if profile.addresses:
        addr = profile.addresses[0]
        location_parts = [p for p in (addr.city, addr.state) if p]
        if location_parts:
            location = ", " + " ".join(location_parts)

    print()
    score_label = f"{score}/100" if score is not None else "unknown"
    print(f"  Broker:  {listing_row['broker']}")
    print(f"  Match:   {name_str}{location} (score: {score_label} - {confidence} confidence)")
    print(f"  Matched fields: {', '.join(matched_fields) if matched_fields else 'none'}")
    print(f"  Missing: {', '.join(missing_fields) if missing_fields else 'none'}")
    if listing_row.get("listing_url"):
        print(f"  URL:     {listing_row['listing_url']}")

    try:
        answer = input("File opt-out? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


REVIEWABLE_STATUSES = ("found", "candidate_found", "needs_review")
APPROVED_STATUSES = ("approved",)


def _decode_matched_fields(raw) -> list[str]:
    """Pull a list of field names out of a state.db row's matched_fields cell."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, str):
        try:
            return json.loads(raw) or []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _format_optout_payload(playbook: Playbook, profile: Profile, listing_row: dict) -> str:
    """Build the same dry-run payload the opt-out flow would send.

    This is what the user sees before approving. It is the strongest
    "no surprises" check we have - a listing only gets opted out using
    exactly these fields.
    """
    broker = _make_broker(playbook, profile, headed=False)
    try:
        result = broker.file_optout(listing_row, dry_run=True)
        return result.get("details", "")
    except Exception as e:
        return f"(could not build dry-run payload: {e})"


def review_listings(
    profile: Profile,
    db: StateDB,
    broker_name: str | None = None,
    playbooks_dir: Path | None = None,
) -> dict:
    """Walk pending listings, show evidence, ask the user to approve each one.

    For each listing, the user sees:
      - broker name, listing URL, score, confidence, matched fields
      - the exact opt-out payload that would be filed if approved
    Then they choose y / N / skip / quit. The result is recorded back
    on the listing's status so ``optout --approved-only`` can pick it
    up.

    Returns a summary dict: counts of approved / rejected / skipped /
    failed lookups. The caller (the CLI) prints it back to the user.
    """
    if broker_name:
        listings = []
        for s in REVIEWABLE_STATUSES:
            listings.extend(db.get_listings(broker=broker_name, status=s))
    elif playbooks_dir is not None:
        known = {pb.broker for pb in load_all_playbooks(directory=playbooks_dir)}
        listings = []
        for s in REVIEWABLE_STATUSES:
            listings.extend(r for r in db.get_listings(status=s) if r["broker"] in known)
    else:
        listings = []
        for s in REVIEWABLE_STATUSES:
            listings.extend(db.get_listings(status=s))

    summary = {"approved": 0, "rejected": 0, "skipped": 0, "no_playbook": 0}

    if not listings:
        return summary

    name_str = f"{profile.name.first} {profile.name.last}".strip()
    location = ""
    if profile.addresses:
        addr = profile.addresses[0]
        parts = [p for p in (addr.city, addr.state) if p]
        if parts:
            location = ", " + " ".join(parts)

    for listing_row in listings:
        playbook = get_playbook(listing_row["broker"], directory=playbooks_dir)
        if not playbook:
            logger.warning(f"No playbook for broker {listing_row['broker']}, skipping")
            summary["no_playbook"] += 1
            continue

        matched = _decode_matched_fields(listing_row.get("matched_fields"))
        missing = [f for f in ALL_MATCHABLE_FIELDS if f not in matched]
        score = listing_row.get("match_score")
        confidence = listing_row.get("confidence") or "unknown"
        score_label = f"{score}/100" if score is not None else "unknown"

        print()
        print(f"  Broker:  {listing_row['broker']}")
        print(f"  Match:   {name_str}{location} (score: {score_label} - {confidence} confidence)")
        print(f"  Matched: {', '.join(matched) if matched else 'none'}")
        print(f"  Missing: {', '.join(missing) if missing else 'none'}")
        if listing_row.get("listing_url"):
            print(f"  URL:     {listing_row['listing_url']}")
        payload = _format_optout_payload(playbook, profile, listing_row)
        if payload:
            print("  Would file:")
            for line in payload.splitlines():
                print(f"    {line}")

        try:
            answer = input("Approve this listing for opt-out? [y/N/skip/quit]: ").strip().lower()
        except EOFError:
            answer = "quit"

        if answer in ("q", "quit"):
            print("Stopped reviewing. Remaining listings stay in needs_review.")
            for r in listings[listings.index(listing_row):]:
                if r["status"] in ("found", "candidate_found"):
                    db.update_listing_status(r["id"], "needs_review")
            break

        if answer in ("y", "yes"):
            db.update_listing_status(listing_row["id"], "approved")
            summary["approved"] += 1
        elif answer in ("s", "skip"):
            if listing_row["status"] in ("found", "candidate_found"):
                db.update_listing_status(listing_row["id"], "needs_review")
            summary["skipped"] += 1
        else:
            db.update_listing_status(listing_row["id"], "rejected")
            summary["rejected"] += 1

    return summary


def file_optouts(
    profile: Profile,
    db: StateDB,
    dry_run: bool = False,
    headed: bool = False,
    broker_name: str | None = None,
    playbooks_dir: Path | None = None,
    auto_confirm: bool = False,
    approved_only: bool = False,
) -> list[dict]:
    """File opt-out requests for all found listings.

    When ``playbooks_dir`` is given without ``broker_name``, only listings
    for brokers that actually live in that directory are processed. That
    lets ``privacyworm mugshot optout`` skip data-broker listings and vice
    versa.

    Unless ``auto_confirm`` is True, each listing is shown to the user and
    they must type ``y`` / ``yes`` before the request is filed.

    ``auto_confirm`` only bypasses the prompt for high-confidence matches.
    Low and medium confidence listings always go through the manual prompt
    so we never blindly file off a name collision.

    ``approved_only=True`` restricts the work to listings the user
    already approved via ``privacyworm review``. That is the recommended
    flow; ``found``/``candidate_found`` listings stay alone until
    someone explicitly looks at them.
    """
    target_statuses = APPROVED_STATUSES if approved_only else ("found",)

    listings: list[dict] = []
    if broker_name:
        for s in target_statuses:
            listings.extend(db.get_listings(broker=broker_name, status=s))
    elif playbooks_dir is not None:
        known = {pb.broker for pb in load_all_playbooks(directory=playbooks_dir)}
        for s in target_statuses:
            listings.extend(r for r in db.get_listings(status=s) if r["broker"] in known)
    else:
        for s in target_statuses:
            listings.extend(db.get_listings(status=s))
    outcomes = []

    for listing_row in listings:
        playbook = get_playbook(listing_row["broker"], directory=playbooks_dir)
        if not playbook:
            logger.warning(f"No playbook for broker {listing_row['broker']}, skipping")
            continue

        # Listings that came through ``review`` already carry the user's
        # approval, so we only re-prompt for the auto-confirm flow when
        # the listing was not pre-approved.
        confidence = listing_row.get("confidence") or "low"
        already_approved = listing_row.get("status") == "approved"
        needs_prompt = (
            not already_approved
            and (not auto_confirm or confidence != "high")
        )
        if needs_prompt and not _confirm_listing(listing_row, profile):
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
            db.update_listing_status(listing_row["id"], "optout_submitted")
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


def _link_domain_allowed(link: str, playbook: Playbook) -> bool:
    """True when the link's registered domain is allowlisted for this broker.

    Allowlist sources, in order:
      1. ``opt_out.confirmation_domains`` from the playbook (explicit).
      2. The broker's homepage registered domain (implicit fallback).
    """
    domains = list(playbook.opt_out.confirmation_domains)
    if not domains:
        domains = [_registered_domain(playbook.homepage)]
    link_domain = _registered_domain(link)
    return link_domain in domains


def _link_path_allowed(link: str, playbook: Playbook) -> bool:
    """True when the link path contains one of the required substrings.

    With no ``confirmation_path_contains`` entries the check is skipped.
    """
    required = playbook.opt_out.confirmation_path_contains
    if not required:
        return True
    return any(needle in link for needle in required)


def _ask_user_to_click(link: str, broker_name: str, body_source: str) -> bool:
    """Print the link and prompt the user. y/yes -> click."""
    print()
    print(f"Confirmation link from {broker_name}:")
    print(f"  {link}")
    if body_source == "html":
        print(
            "  Note: this link came from an HTML-only email. HTML emails "
            "are easier to spoof; double-check the URL above is the broker."
        )
    try:
        answer = input("Click this confirmation link? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def check_inbox(
    profile: Profile,
    db: StateDB,
    auto_confirm_inbox: bool = False,
) -> list[dict]:
    """Check the inbox for confirmation emails and process them.

    Each candidate link goes through three checks before anything gets
    clicked:

      1. The link's registered domain must be in the playbook's
         ``confirmation_domains`` allowlist (homepage as default).
      2. If ``confirmation_path_contains`` is set, the link path must
         contain one of the substrings.
      3. By default the user sees the URL and is asked y/N. Pass
         ``auto_confirm_inbox=True`` to skip the prompt - that mode is
         a footgun, the caller should warn loudly.

    HTML-only emails always go through the prompt regardless of
    ``auto_confirm_inbox``, since HTML email is easier to spoof.

    Each (broker, IMAP UID) pair is recorded in
    ``processed_emails`` so the same confirmation email never gets
    clicked twice.
    """
    if not profile.inbox:
        logger.warning("No inbox configured in profile. Run 'privacyworm init' to set one up.")
        return []

    inbox = ImapInbox(profile.inbox)
    processed = []

    # Get all pending opt-outs and their associated playbooks
    pending = db.get_optouts(status="pending")
    for optout in pending:
        listing = []
        for s in ("optout_submitted", "opt_out_filed", "confirmation_needed"):
            listing.extend(db.get_listings(status=s))
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
            uid = conf.get("uid", "")
            if uid and db.email_already_processed(matching_listing["broker"], uid):
                logger.info(
                    f"Already processed confirmation email uid={uid} for "
                    f"{matching_listing['broker']}, skipping."
                )
                continue

            for link in conf["links"]:
                if not _link_domain_allowed(link, playbook):
                    logger.warning(
                        "Skipping confirmation link: domain not in allowlist "
                        f"(link={link!r}, allowed={playbook.opt_out.confirmation_domains!r}, "
                        f"homepage={playbook.homepage!r})"
                    )
                    continue
                if not _link_path_allowed(link, playbook):
                    logger.warning(
                        "Skipping confirmation link: path does not match "
                        f"required substrings {playbook.opt_out.confirmation_path_contains!r} "
                        f"(link={link!r})"
                    )
                    continue

                # Either explicit consent or HTML-only email always asks.
                must_prompt = (not auto_confirm_inbox) or conf.get("body_source") == "html"
                if must_prompt and not _ask_user_to_click(
                    link, matching_listing["broker"], conf.get("body_source", "text")
                ):
                    continue

                if inbox.click_confirmation_link(link):
                    db.confirm_optout(optout["id"])
                    db.update_listing_status(matching_listing["id"], "confirmation_clicked")
                    if uid:
                        db.mark_email_processed(matching_listing["broker"], uid)
                    processed.append({
                        "broker": matching_listing["broker"],
                        "optout_id": optout["id"],
                        "link": link,
                    })
                    break

    return processed
