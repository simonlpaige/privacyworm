"""Guided mode: what you get when you just run ``privacyworm``.

The goal is that someone who has never opened a terminal can install
PrivacyWorm, double-click it, and get through a full check-up by
answering simple questions:

  first run  ->  welcome, enter your info, pick a passphrase
  every run  ->  unlock once, see where things stand, run a check-up

A check-up is the whole loop in one go: search every broker, show what
was found, let you say "yes that's me / not me", then walk through each
removal with the form already filled in. The power-user subcommands
(scan, review, optout, ...) still exist and share the same code.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from privacyworm import __version__, desktop, ui
from privacyworm.browser import ensure_browser, open_in_default_browser
from privacyworm.cli_helpers import open_state, unlock_profile
from privacyworm.config import enable_state_encryption, get_profile_path
from privacyworm.playbook import MUGSHOT_PLAYBOOKS_DIR, load_all_playbooks
from privacyworm.profile import Profile, encrypt_profile
from privacyworm.profile_setup import ask_inbox, ask_new_passphrase, interview
from privacyworm.runner import (
    REVIEWABLE_STATUSES,
    SUBMITTED_STATUSES,
    check_inbox,
    file_optouts,
    review_listings,
    scan_reports,
)
from privacyworm.state import StateDB

logger = logging.getLogger("privacyworm")

DROP_NOTE = (
    "You live in California, so you can also use the state's free DROP service "
    "(drop.oag.ca.gov). One request there reaches 500+ registered brokers. "
    "PrivacyWorm still helps with the sites outside that system and with re-checks."
)


class Session:
    """Everything unlocked for this run: profile, state DB, passphrase."""

    def __init__(self, profile: Profile, passphrase: str, db: StateDB):
        self.profile = profile
        self.passphrase = passphrase
        self.db = db
        self.drop_shown = False
        self.closed = False

    def save_profile(self) -> None:
        encrypt_profile(self.profile, self.passphrase, get_profile_path(encrypted=True))

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            desktop.set_next_due(self.db.next_rescan_at())
        finally:
            self.db.close()


# -- Entry --------------------------------------------------------------------


def run(reminder: bool = False) -> None:
    """Top-level guided flow. Never shows a stack trace to the user."""
    # Keep library chatter (URLs, debug lines) out of the guided screens.
    logging.getLogger("privacyworm").setLevel(logging.WARNING)
    try:
        _run(reminder)
    except (KeyboardInterrupt, EOFError):
        ui.say("\n  Bye for now.")
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        ui.bad(f"Something went wrong: {e}")
        ui.para(
            "Your info is safe. If this keeps happening, please open an issue at "
            "github.com/simonlpaige/privacyworm/issues (don't include personal details)."
        )
        if ui.interactive():
            ui.pause("Press Enter to close")


def _banner() -> None:
    ui.say()
    ui.say(ui.style("  PrivacyWorm", bold=True, fg="green") + ui.style(f"  v{__version__}", dim=True))
    ui.dim("  Find your info on people-search sites and get it taken down.")


def _run(reminder: bool) -> None:
    _banner()
    if not get_profile_path(encrypted=True).exists():
        session = _first_run()
        if session is None:
            return
    else:
        if reminder:
            ui.say()
            ui.good("It's time for your regular check-up.")
        ui.say()
        profile, passphrase = unlock_profile()
        session = Session(profile, passphrase, open_state(passphrase))
    try:
        _home(session, suggest_checkup=reminder)
    finally:
        session.close()


# -- First run ----------------------------------------------------------------


def _first_run() -> Session | None:
    ui.title("Welcome")
    ui.para(
        "People-search sites like Spokeo and Whitepages publish your name, address, "
        "phone and relatives. PrivacyWorm finds those pages and walks you through "
        "getting each one taken down. Then it reminds you to re-check, because they "
        "tend to come back."
    )
    ui.say()
    ui.para(
        "Everything stays on this computer, locked with a passphrase you choose. "
        "Nothing is sent anywhere except the removal requests you approve."
    )
    ui.say()
    ui.para("Setup takes about 3 minutes. Your first check-up takes about 10-20.")
    ui.say()
    if not ui.yes_no("Ready to start?", default=True):
        ui.say("  No problem. Run PrivacyWorm again whenever you're ready.")
        return None

    profile = interview()
    ui.title("Lock it")
    passphrase = ask_new_passphrase()
    encrypt_profile(profile, passphrase, get_profile_path(encrypted=True))
    # New installs encrypt the listing history too. Same passphrase, so
    # it costs the user nothing.
    enable_state_encryption()
    ui.good("Saved and locked.")

    session = Session(profile, passphrase, StateDB(passphrase=passphrase))

    if not desktop.reminders_enabled():
        ui.title("Reminders")
        ui.para(
            "Brokers re-list people every couple of months. PrivacyWorm can open "
            "itself when it's time for a re-check (about once a month, only when "
            "something is due). No data is stored for this - just the date."
        )
        if ui.yes_no("Turn on reminders?", default=True):
            ok, msg = desktop.enable_reminders()
            (ui.good if ok else ui.warn)(msg)

    ui.say()
    if ui.yes_no("Run your first check-up now?", default=True):
        checkup(session)
    return session


# -- Home ---------------------------------------------------------------------


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = (dt - datetime.now(timezone.utc)).days
    when = dt.astimezone().strftime("%b %d, %Y").replace(" 0", " ")
    if days < -1:
        return f"{when} ({-days} days ago)"
    if days > 1:
        return f"{when} (in {days} days)"
    return f"{when} (today)"


def _counts(db: StateDB) -> dict[str, int]:
    c = db.status_counts()
    return {
        "to_review": sum(c.get(s, 0) for s in REVIEWABLE_STATUSES),
        "approved": c.get("approved", 0),
        "requested": sum(c.get(s, 0) for s in SUBMITTED_STATUSES),
        "confirm": c.get("confirmation_needed", 0),
        "removed": c.get("removed", 0),
        "not_me": c.get("rejected", 0),
        "total": sum(c.values()),
    }


def _status_lines(session: Session) -> bool:
    """Print the one-glance status. Returns True if a check-up is due."""
    db = session.db
    last = db.last_scan_at()
    nxt = db.next_rescan_at()
    due = last is None or (nxt is not None and nxt <= datetime.now(timezone.utc).isoformat())
    c = _counts(db)
    ui.say(f"  Hi {session.profile.name.first}.")
    ui.say(f"  Last check-up: {_fmt_date(last)}")
    if nxt:
        ui.say(f"  Next one due:  {_fmt_date(nxt)}")
    if c["total"]:
        ui.say(
            f"  So far: {c['removed']} gone, {c['requested']} removal(s) in progress, "
            f"{c['to_review'] + c['approved']} waiting on you, {c['not_me']} not you."
        )
    if c["confirm"]:
        ui.warn(f"{c['confirm']} broker(s) emailed (or will email) you a link to confirm. Check your inbox.")
    return due


def _home(session: Session, suggest_checkup: bool = False) -> None:
    while True:
        ui.title("Home")
        due = _status_lines(session)
        reminders = "on" if desktop.reminders_enabled() else "off"
        ui.say()
        options = [
            ("1", "Run a check-up" + (ui.style("  ← due now", fg="yellow") if due else "")),
            ("2", "See everything that's been found"),
            ("3", f"Reminders (currently {reminders})"),
            ("4", "Edit my info"),
            ("5", "More tools: mugshot sites, social media, email confirmations"),
            ("q", "Quit"),
        ]
        default = "1" if (due or suggest_checkup) else "q"
        choice = ui.choose("Choose", options, default=default)
        suggest_checkup = False
        if choice == "1":
            checkup(session)
        elif choice == "2":
            show_status(session)
        elif choice == "3":
            reminders_menu()
        elif choice == "4":
            edit_profile(session)
        elif choice == "5":
            more_tools(session)
        else:
            ui.say("\n  Bye for now. Your info stays locked on this computer.")
            return


# -- Check-up -----------------------------------------------------------------


def _assist(info: dict) -> str:
    """Walk the user through finishing one removal. Returns done/failed/skipped."""
    kind = info["kind"]
    ui.say()
    ui.say(ui.style(f"  {info['broker']}", bold=True))
    if kind == "web_form":
        ui.say("  A browser window opened with their opt-out form, filled in:")
        for label, value in info.get("fields", {}).items():
            ui.say(f"    {label}: {value}")
        if info.get("missed"):
            ui.warn("Couldn't find some boxes on the page. Please fill these in yourself:")
            for label, value in info["missed"].items():
                ui.say(f"      {label}: {value}")
        ui.say("  In that window:")
        ui.say("    1. Check the details look right")
        ui.say("    2. Tick any \"I'm not a robot\" box")
        ui.say("    3. Click the Submit / Remove button")
    elif kind == "email":
        opened = open_in_default_browser(info["mailto"])
        if opened:
            ui.say("  Your email app should have opened a ready-to-send message. Just press Send.")
            ui.dim("  (If nothing opened, copy the message below into a new email.)")
        else:
            ui.say("  Copy this into a new email and send it:")
        ui.say(f"    To:      {info['to']}")
        ui.say(f"    Subject: {info['subject']}")
        for line in info["body"].splitlines():
            ui.say(f"    | {line}")
    else:  # manual
        open_in_default_browser(info["url"])
        ui.say(f"  This one has to be done by hand. We opened {info['url']}")
        if info.get("listing_url"):
            ui.say(f"  Your listing: {info['listing_url']}")
        ui.say("  What to do:")
        for line in (info.get("instructions") or "").strip().splitlines():
            ui.say(f"    {line}")
    if info.get("requires_confirmation"):
        ui.warn("They'll email you a link afterwards. Click it to finish the removal.")
    ui.say()
    choice = ui.choose(
        "How did it go",
        [("d", "Done - it's sent"), ("p", "Problem - it didn't work"), ("s", "Skip for now")],
        default="d",
    )
    return {"d": "done", "p": "failed", "s": "skipped"}[choice]


def checkup(session: Session, playbooks_dir=None, label: str = "people-search sites") -> None:
    """Scan -> review -> remove, in one guided pass."""
    profile, db = session.profile, session.db

    if (
        playbooks_dir is None
        and not session.drop_shown
        and profile.addresses
        and profile.addresses[0].state.upper() == "CA"
    ):
        ui.say()
        ui.para(DROP_NOTE)
        session.drop_shown = True

    ui.title("Getting the browser ready")
    if not ensure_browser(echo=lambda m: ui.say(f"  {m}")):
        ui.pause()
        return

    playbooks = load_all_playbooks(directory=playbooks_dir)
    ui.title(f"Searching {len(playbooks)} {label}")
    ui.dim("  This runs in the background and takes a few minutes. Nothing is sent to anyone yet.")

    def on_start(pb):
        print(f"  {pb.display_name:<24} ", end="", flush=True)

    def on_done(r):
        if r["status"] == "ok":
            n = len(r["listings"])
            if n:
                extra = f" ({r['new']} new)" if r["new"] and r["new"] != n else ""
                print(ui.style(f"{n} possible listing(s){extra}", fg="yellow"))
            else:
                print(ui.style("nothing found", fg="green"))
            if r["gone"]:
                ui.good(f"{r['gone']} earlier listing(s) are gone now")
        elif r["status"] == "blocked":
            print(ui.style("couldn't check - the site asked for a CAPTCHA", fg="red"))
        elif r["status"] == "unreadable":
            print(ui.style("couldn't read the results - the site changed", fg="red"))
        else:
            print(ui.style(f"couldn't check - {r['note'][:60]}", fg="red"))

    reports = scan_reports(profile, db, playbooks_dir=playbooks_dir, on_start=on_start, on_done=on_done)

    blocked = [r for r in reports if r["status"] == "blocked"]
    if blocked:
        ui.say()
        ui.para(
            f"{len(blocked)} site(s) blocked the automatic search with a robot check. "
            "You can try them again in a visible browser window and click through it yourself."
        )
        if ui.yes_no("Try those again with a visible window?", default=True):
            retried = []
            for r in blocked:
                retried += scan_reports(
                    profile, db, headed=True, broker_name=r["broker"],
                    playbooks_dir=playbooks_dir, on_start=on_start, on_done=on_done,
                )
            reports = [r for r in reports if r["status"] != "blocked"] + retried

    unsure = [r for r in reports if r["status"] in ("unreadable", "error", "blocked") and r.get("search_url")]
    if unsure:
        ui.say()
        ui.para(
            f"PrivacyWorm couldn't read the results from {len(unsure)} site(s). That doesn't "
            "mean you're not listed. You can open their search pages and look yourself."
        )
        if ui.yes_no("Open those search pages in your browser?", default=False):
            for r in unsure:
                open_in_default_browser(r["search_url"])
            ui.para(
                "If you find yourself there, look for an 'opt out' or 'do not sell' link at the "
                "bottom of the page. Please also open an issue so the site can be fixed for everyone."
            )

    # Review
    pending = sum(1 for s in REVIEWABLE_STATUSES for _ in db.get_listings(status=s))
    if pending:
        ui.title("Is this you?")
        ui.para(
            "For each listing, say whether it's you. Nothing is sent until you've "
            "said yes. Type o to open the page and look first."
        )
        summary = review_listings(profile, db, playbooks_dir=playbooks_dir)
        ui.say()
        ui.say(
            f"  {summary['approved']} to remove, {summary['rejected']} not you, "
            f"{summary['skipped']} saved for later."
        )
    else:
        ui.say()
        ui.good("Nothing new to review.")

    # Remove
    approved = db.get_listings(status="approved")
    if playbooks_dir is not None:
        known = {pb.broker for pb in playbooks}
        approved = [r for r in approved if r["broker"] in known]
    if approved:
        ui.title(f"Removing {len(approved)} listing(s)")
        ui.para(
            "One at a time, PrivacyWorm opens each site's opt-out form (or an email "
            "draft) with your details filled in. You do the last click - that's what "
            "gets past their 'are you a robot' checks."
        )
        if ui.yes_no("Start now?", default=True):
            outcomes = file_optouts(
                profile, db, approved_only=True, playbooks_dir=playbooks_dir, assist=_assist
            )
            done = sum(1 for o in outcomes if o["success"])
            ui.say()
            ui.good(f"{done} removal request(s) sent.")
            left = len(outcomes) - done
            if left:
                ui.say(f"  {left} still to do - they'll be here next time.")
        else:
            ui.say("  Okay - they'll be waiting next time you run a check-up.")

    ui.title("Check-up done")
    nxt = db.next_rescan_at()
    desktop.set_next_due(nxt)
    ui.say(f"  Next check-up due: {_fmt_date(nxt)}")
    ui.para(
        "Removals usually take a few days to a few weeks. Your next check-up "
        "will show which listings are gone."
    )
    if not desktop.reminders_enabled():
        if ui.yes_no("Want a reminder when it's time?", default=True):
            ok, msg = desktop.enable_reminders()
            (ui.good if ok else ui.warn)(msg)
    ui.pause("Press Enter to go back to the menu")


# -- Status -------------------------------------------------------------------

STATUS_WORDS = {
    "found": "waiting for you to review",
    "candidate_found": "waiting for you to review",
    "needs_review": "waiting for you to review",
    "reappeared": "came back - needs review",
    "approved": "approved, not sent yet",
    "rejected": "not you",
    "optout_submitted": "removal requested",
    "opt_out_filed": "removal requested",
    "confirmation_needed": "requested - click the link they emailed you",
    "confirmation_clicked": "confirmed, waiting for removal",
    "removal_pending": "waiting for removal",
    "opt_out_confirmed": "confirmed, waiting for removal",
    "removed": "gone (not found on last check)",
    "failed": "something went wrong",
    "manual_required": "needs a manual step",
}


def show_status(session: Session) -> None:
    ui.title("Everything found so far")
    rows = session.db.get_listings()
    if not rows:
        ui.say("  Nothing yet. Run a check-up to start.")
        ui.pause()
        return
    names = {pb.broker: pb.display_name for pb in load_all_playbooks()}
    names.update({pb.broker: pb.display_name for pb in load_all_playbooks(MUGSHOT_PLAYBOOKS_DIR)})
    for row in sorted(rows, key=lambda r: (r["broker"], r["status"])):
        label = names.get(row["broker"], row["broker"])
        ui.say(f"  {label:<22} {STATUS_WORDS.get(row['status'], row['status'])}")
        if row.get("listing_url"):
            ui.dim(f"  {'':<22} {row['listing_url']}")
    ui.pause()


# -- Reminders / profile / more ----------------------------------------------


def reminders_menu() -> None:
    ui.title("Reminders")
    on = desktop.reminders_enabled()
    ui.para(
        "When reminders are on, your computer checks once a day whether a check-up "
        "is due and, if so, opens PrivacyWorm for you. Nothing personal is stored "
        "for this."
    )
    due = desktop.next_due()
    if due:
        ui.say(f"  Next check-up due: {_fmt_date(due.isoformat())}")
    ui.say(f"  Reminders are {'ON' if on else 'OFF'}.")
    if on:
        if ui.yes_no("Turn them off?", default=False):
            ok, msg = desktop.disable_reminders()
            ui.good(msg)
    else:
        if ui.yes_no("Turn them on?", default=True):
            ok, msg = desktop.enable_reminders()
            (ui.good if ok else ui.warn)(msg)


def edit_profile(session: Session) -> None:
    ui.title("Edit my info")
    ui.dim("  Press Enter to keep what's in [brackets].")
    session.profile = interview(session.profile)
    if ui.yes_no("Change your passphrase too?", default=False):
        new = ask_new_passphrase()
        session.passphrase = new
        session.db.passphrase = new  # state.db.enc re-encrypts with it on close
    session.save_profile()
    ui.good("Saved.")


def more_tools(session: Session) -> None:
    while True:
        ui.title("More tools")
        choice = ui.choose("Choose", [
            ("1", "Mugshot sites - search and request removal"),
            ("2", "Social media - how to delete accounts and old posts"),
            ("3", "Email confirmations - find and click broker confirmation links"),
            ("4", "Official state data-broker registries"),
            ("5", "Check that the browser works"),
            ("6", "Start over - delete my info and history from this computer"),
            ("b", "Back"),
        ], default="b")
        if choice == "1":
            checkup(session, playbooks_dir=MUGSHOT_PLAYBOOKS_DIR, label="mugshot sites")
        elif choice == "2":
            _social_help()
        elif choice == "3":
            _email_confirmations(session)
        elif choice == "4":
            from privacyworm.cli import print_registries

            print_registries()
            ui.pause()
        elif choice == "5":
            ensure_browser(echo=lambda m: ui.say(f"  {m}"))
            ui.pause()
        elif choice == "6":
            if _start_over(session):
                raise SystemExit(0)
        else:
            return


def _social_help() -> None:
    from privacyworm.social.playbook import load_all_social_playbooks

    pbs = load_all_social_playbooks()
    ui.title("Social media")
    options = [(str(i), pb.display_name) for i, pb in enumerate(pbs, 1)] + [("b", "Back")]
    choice = ui.choose("Which platform", options, default="b")
    if choice == "b":
        return
    pb = pbs[int(choice) - 1]
    ui.title(pb.display_name)
    for i, step in enumerate(pb.instructions, 1):
        ui.say(f"  {i}. {step}")
    if pb.notes:
        ui.say()
        ui.para(pb.notes)
    if pb.manual_url and ui.yes_no(f"Open {pb.manual_url} now?", default=True):
        open_in_default_browser(pb.manual_url)
    if pb.platform in ("reddit", "twitter"):
        ui.say()
        ui.para(
            f"Bulk-deleting old {pb.display_name} posts is available from the command "
            f"line: privacyworm social delete --platform {pb.platform} --older-than 1y "
            "(needs a free developer app ID - see the README)."
        )
    ui.pause()


def _email_confirmations(session: Session) -> None:
    profile = session.profile
    if not profile.inbox or ui.yes_no("Change your email settings first?", default=False):
        inbox = ask_inbox(profile.inbox)
        if inbox is None:
            return
        profile.inbox = inbox
        session.save_profile()
        ui.good("Saved inside your encrypted profile.")
    ui.title("Checking your inbox")
    processed = check_inbox(profile, session.db)
    if processed:
        for p in processed:
            ui.good(f"Confirmed {p['broker']}")
    else:
        ui.say("  No new confirmation emails found.")
    ui.pause()


def _start_over(session: Session) -> bool:
    from privacyworm.config import get_config_dir

    ui.title("Start over")
    ui.para(
        "This deletes your saved info, passphrase and listing history from this "
        "computer. Removal requests you already sent are not undone."
    )
    if not ui.yes_no("Delete everything?", default=False):
        return False
    session.close()
    import os
    import shutil

    for p in [get_profile_path(encrypted=True)]:
        if p.exists():
            p.write_bytes(os.urandom(p.stat().st_size))
    desktop.disable_reminders()
    shutil.rmtree(get_config_dir(), ignore_errors=True)
    ui.good("Done. Your info is gone from this computer.")
    ui.para(
        "PrivacyWorm itself is still installed. To set up fresh, run it again. "
        "To remove the app too, run: privacyworm uninstall"
    )
    return True
