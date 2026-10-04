"""Orchestrator: scan -> match -> opt-out -> log."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import tldextract

from privacyworm.brokers.base import AssistCallback, BaseBroker
from privacyworm.brokers.email import EmailBroker
from privacyworm.brokers.web_form import WebFormBroker
from privacyworm.inbox.imap import ImapInbox
from privacyworm.matching import score_listing
from privacyworm.playbook import Playbook, get_playbook, load_all_playbooks
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


# Listing statuses that mean "we asked the broker to take this down".
SUBMITTED_STATUSES = (
    "optout_submitted",
    "confirmation_needed",
    "confirmation_clicked",
    "removal_pending",
    "opt_out_filed",
    "opt_out_confirmed",
)


def scan_broker_report(
    playbook: Playbook,
    profile: Profile,
    db: StateDB,
    headed: bool = False,
) -> dict:
    """Scan one broker and say how it went.

    Returns ``{broker, display_name, status, note, listings, new,
    gone, reappeared, search_url}`` where status is "ok", "blocked",
    "unreadable" (page loaded but our selectors found nothing while the
    name is on the page) or "error".
    Only an "ok" scan is trusted: it moves the rescan date forward and
    marks earlier opt-outs that no longer show up as removed. A blocked
    or failed scan changes nothing, so the broker stays due.
    """
    report: dict[str, Any] = {
        "broker": playbook.broker,
        "display_name": playbook.display_name,
        "status": "ok",
        "note": "",
        "listings": [],
        "new": 0,
        "gone": 0,
        "reappeared": 0,
        "search_url": None,
    }
    broker = _make_broker(playbook, profile, headed)
    try:
        report["search_url"] = broker._build_search_url()
    except ValueError:
        pass
    try:
        listings = broker.scan()
        report["status"], report["note"] = broker.scan_status, broker.scan_note
    except Exception as e:  # noqa: BLE001 - one broken site must not stop the run
        lines = str(e).strip().splitlines()
        report["status"], report["note"] = "error", (lines[0] if lines else type(e).__name__)
        logger.debug("scan failed", exc_info=True)
        return report

    seen_urls = set()
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

        url = listing.get("listing_url")
        seen_urls.add(url)
        existing = db.find_listing(playbook.broker, url)
        if existing is None:
            db.add_listing(
                broker=playbook.broker,
                listing_url=url,
                confidence=verdict["confidence"],
                match_score=verdict["score"],
                matched_fields=verdict["matched_fields"],
            )
            report["new"] += 1
        elif existing["status"] == "removed":
            db.update_listing_status(existing["id"], "reappeared")
            report["reappeared"] += 1

    report["listings"] = listings

    if report["status"] == "ok":
        for row in db.get_listings(broker=playbook.broker):
            if row["status"] in SUBMITTED_STATUSES and row["listing_url"] not in seen_urls:
                db.update_listing_status(row["id"], "removed")
                report["gone"] += 1
        next_scan = datetime.now(timezone.utc) + timedelta(days=playbook.rescan_days)
        db.set_rescan(playbook.broker, next_scan.isoformat())

    return report


def scan_broker(
    playbook: Playbook,
    profile: Profile,
    db: StateDB,
    headed: bool = False,
) -> list[dict]:
    """Scan a single broker, score each listing, and store the verdicts."""
    report = scan_broker_report(playbook, profile, db, headed)
    if report["status"] == "error":
        raise RuntimeError(report["note"])
    return report["listings"]


def scan_reports(
    profile: Profile,
    db: StateDB,
    headed: bool = False,
    broker_name: str | None = None,
    playbooks_dir: Path | None = None,
    on_start=None,
    on_done=None,
) -> list[dict]:
    """Scan every broker (or one) and return a report per broker.

    ``on_start(playbook)`` / ``on_done(report)`` let the UI show progress.
    """
    if broker_name:
        pb = get_playbook(broker_name, directory=playbooks_dir)
        if not pb:
            raise ValueError(f"No playbook found for broker: {broker_name}")
        playbooks = [pb]
    else:
        playbooks = load_all_playbooks(directory=playbooks_dir)
    reports = []
    for pb in playbooks:
        if on_start:
            on_start(pb)
        report = scan_broker_report(pb, profile, db, headed)
        if on_done:
            on_done(report)
        reports.append(report)
    return reports


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
    try:
        reports = scan_reports(
            profile, db, headed=headed, broker_name=broker_name, playbooks_dir=playbooks_dir
        )
    except ValueError as e:
        logger.error(str(e))
        return {}
    results: dict[str, list[dict]] = {}
    for r in reports:
        if r["status"] != "ok":
            logger.warning(f"{r['display_name']}: couldn't check ({r['note']})")
        results[r["broker"]] = r["listings"]
    return results


FIELD_WORDS = {
    "full_name": "your name",
    "city": "city",
    "state": "state",
    "zip": "ZIP code",
    "phone": "phone number",
    "relative": "a relative",
    "age": "age",
}
CONFIDENCE_WORDS = {
    "high": "Strong match",
    "medium": "Possible match",
    "low": "Weak match - might be someone else",
}


def describe_match(listing_row: dict) -> tuple[str, str]:
    """Plain-English (headline, matched-on) for a listing row."""
    matched = _decode_matched_fields(listing_row.get("matched_fields"))
    score = listing_row.get("match_score")
    confidence = listing_row.get("confidence") or "unknown"
    headline = CONFIDENCE_WORDS.get(confidence, "Unscored match")
    if score is not None:
        headline += f" ({score}/100)"
    words = [FIELD_WORDS.get(f, f) for f in matched]
    return headline, (", ".join(words) if words else "nothing beyond the name search")


def _confirm_listing(listing_row: dict, profile: Profile) -> bool:
    """Show the score and matched fields, then ask whether to file an opt-out.

    Returns True when the user types y/yes (case-insensitive), else False.
    """
    headline, matched_on = describe_match(listing_row)
    print()
    print(f"  {listing_row['broker']}: {headline}")
    print(f"  Matched on: {matched_on}")
    if listing_row.get("listing_url"):
        print(f"  Page:       {listing_row['listing_url']}")
    try:
        answer = input("File opt-out? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


REVIEWABLE_STATUSES = ("found", "candidate_found", "needs_review", "reappeared")
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
    """Describe exactly what the opt-out would send, in plain lines.

    This is what the user sees before approving. It is the strongest
    "no surprises" check we have - a listing only gets opted out using
    exactly these fields.
    """
    opt = playbook.opt_out
    if opt.method == "manual":
        return f"Nothing automatic. You'll get instructions and a link to {opt.url or playbook.homepage}"
    broker = _make_broker(playbook, profile, headed=False)
    try:
        result = broker.file_optout(listing_row, dry_run=True)
    except Exception as e:  # noqa: BLE001
        return f"(could not build dry-run payload: {e})"
    details = result.get("details", "")
    if opt.method == "web_form" and isinstance(broker, WebFormBroker):
        lines = [f"Their opt-out form at {opt.url}, filled in with:"]
        for key, value in broker._build_dry_run_payload(listing_row).items():
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)
    if opt.method == "email" and isinstance(broker, EmailBroker):
        subject = opt.email_subject or "Data Removal Request"
        lines = [f"An email to {opt.email_address}", f"  Subject: {subject}"]
        lines += [f"  | {line}" for line in broker._build_email_body(listing_row).splitlines()]
        return "\n".join(lines)
    return details.replace("DRY RUN - ", "")


def review_listings(
    profile: Profile,
    db: StateDB,
    broker_name: str | None = None,
    playbooks_dir: Path | None = None,
) -> dict:
    """Walk pending listings, show evidence, ask the user to approve each one.

    For each listing, the user sees the broker, how strong the match is
    and why, the page itself (they can open it), and exactly what the
    opt-out would send. Answers:

      y  yes, it's me - remove it       (-> approved)
      n  not me                         (-> rejected, never asked again)
      o  open the page in my browser    (then asks again)
      s  decide later / Enter           (-> needs_review)
      q  stop reviewing                 (rest -> needs_review)

    Returns a summary dict: counts of approved / rejected / skipped /
    no_playbook. The caller prints it back to the user.
    """
    from privacyworm.browser import open_in_default_browser
    from privacyworm.ui import style

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

    # Strongest matches first - they're the quick yeses.
    listings.sort(key=lambda r: -(r.get("match_score") or 0))
    total = len(listings)

    for idx, listing_row in enumerate(listings, 1):
        playbook = get_playbook(listing_row["broker"], directory=playbooks_dir)
        if not playbook:
            logger.warning(f"No playbook for broker {listing_row['broker']}, skipping")
            summary["no_playbook"] += 1
            continue

        headline, matched_on = describe_match(listing_row)
        print()
        print(style(f"  [{idx} of {total}]  {playbook.display_name}", bold=True))
        if listing_row.get("status") == "reappeared":
            print("  This listing came back after an earlier removal.")
        print(f"  {headline}")
        print(f"  Matched on: {matched_on}")
        if listing_row.get("listing_url"):
            print(f"  Page:       {listing_row['listing_url']}")
        payload = _format_optout_payload(playbook, profile, listing_row)
        if payload:
            print("  If you say yes, PrivacyWorm will use:")
            for line in payload.splitlines():
                print(f"    {line}")

        while True:
            try:
                answer = input(
                    "  Is this you? [y]es remove it / [n]ot me / [o]pen page / [s]kip / [q]uit: "
                ).strip().lower()
            except EOFError:
                answer = "quit"
            if answer in ("o", "open"):
                url = listing_row.get("listing_url")
                if url and open_in_default_browser(url):
                    print("  Opened in your browser. Take a look, then answer here.")
                else:
                    print("  Couldn't open a browser. Copy the Page link above instead.")
                continue
            break

        if answer in ("q", "quit"):
            print("  Stopped reviewing. The rest will be waiting next time.")
            for r in listings[idx - 1:]:
                if r["status"] in ("found", "candidate_found", "reappeared"):
                    db.update_listing_status(r["id"], "needs_review")
            break

        if answer in ("y", "yes"):
            db.update_listing_status(listing_row["id"], "approved")
            summary["approved"] += 1
        elif answer in ("n", "no", "not me"):
            db.update_listing_status(listing_row["id"], "rejected")
            summary["rejected"] += 1
        else:
            # Enter / skip / anything unexpected: keep it, ask again later.
            if listing_row["status"] in ("found", "candidate_found", "reappeared"):
                db.update_listing_status(listing_row["id"], "needs_review")
            summary["skipped"] += 1

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
    assist: AssistCallback | None = None,
) -> list[dict]:
    """File opt-out requests for all found listings.

    ``assist`` switches to the guided, human-finishes-the-last-step mode:
    web forms open in a visible window pre-filled, email opt-outs open
    as a draft in the user's mail app, and manual brokers get their page
    opened with instructions. See ``brokers.base.AssistCallback``.

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
            if assist is not None and not dry_run:
                where = playbook.opt_out.url or playbook.homepage
                outcome = assist({
                    "kind": "manual",
                    "broker": playbook.display_name,
                    "url": where,
                    "instructions": msg,
                    "listing_url": listing_row.get("listing_url"),
                    "requires_confirmation": False,
                })
                if outcome == "done":
                    db.update_listing_status(listing_row["id"], "optout_submitted")
                    db.add_optout(listing_id=listing_row["id"], method="manual", details="Done by hand")
                outcomes.append({
                    "broker": listing_row["broker"],
                    "listing_id": listing_row["id"],
                    "success": outcome == "done",
                    "method": "manual" if outcome != "skipped" else "skipped",
                    "details": {"done": "You finished it by hand.", "skipped": "Skipped for now."}.get(
                        outcome, "Not finished yet."
                    ),
                })
                continue
            outcomes.append({
                "broker": listing_row["broker"],
                "listing_id": listing_row["id"],
                "success": False,
                "method": "manual",
                "details": msg,
            })
            continue

        broker = _make_broker(playbook, profile, headed)
        try:
            result = broker.file_optout(listing_row, dry_run=dry_run, assist=assist)
        except Exception as e:  # noqa: BLE001 - report it and keep going
            result = {"success": False, "method": playbook.opt_out.method, "details": f"Error: {e}"}

        if not dry_run and result["success"]:
            db.update_listing_status(
                listing_row["id"],
                "confirmation_needed" if playbook.opt_out.requires_confirmation else "optout_submitted",
            )
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
        matching_listing = next(
            (row for row in listing if row["id"] == optout["listing_id"]),
            None,
        )
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
