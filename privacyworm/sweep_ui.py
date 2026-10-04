"""Guided screens for the email sweep: setup, run, to-do list, complaints."""

from __future__ import annotations

import getpass
from datetime import datetime, timedelta
from pathlib import Path

from privacyworm import autopilot, desktop, letters, ui
from privacyworm.browser import open_in_default_browser
from privacyworm.mailer import Mailbox, provider_for
from privacyworm.profile import InboxConfig
from privacyworm.profile_setup import valid_email
from privacyworm.registry import list_info


def email_ready(session) -> bool:
    inbox = session.profile.inbox
    return bool(inbox and inbox.user and inbox.password)


def setup_email(session) -> bool:
    """Connect the user's mailbox. Returns True when it works."""
    p = session.profile
    ui.title("Send requests from your email")
    ui.para(
        "PrivacyWorm emails each data broker a deletion request from your own address, "
        "so their replies come back to you and PrivacyWorm can read them. To do that it "
        "needs an 'app password': a separate password just for PrivacyWorm that you can "
        "cancel any time. Your normal password is never used."
    )
    default = p.inbox.user if p.inbox and p.inbox.user else (p.emails[0] if p.emails else "")
    while True:
        address = ui.ask("Email address to send from", default)
        if valid_email(address):
            break
        ui.say("    That doesn't look like an email address.")
    imap_host, _smtp, _port, help_url = provider_for(address)
    if help_url:
        ui.say()
        ui.para("Opening the page where you make an app password. Name it 'PrivacyWorm' and copy the password it shows you.")
        if address.lower().endswith(("gmail.com", "googlemail.com")):
            ui.dim("  (Google only offers app passwords when 2-Step Verification is on.)")
        open_in_default_browser(help_url)
    else:
        ui.para("Look in your email provider's security settings for 'app passwords'.")
    for _attempt in range(3):
        try:
            password = getpass.getpass(ui.style("  Paste the app password here (hidden): ", bold=True))
        except EOFError:
            return False
        password = password.replace(" ", "").strip()
        if not password:
            return False
        cfg = InboxConfig(
            host=(p.inbox.host if p.inbox and p.inbox.user == address else imap_host),
            user=address,
            password=password,
            daily_limit=p.inbox.daily_limit if p.inbox else 60,
        )
        ui.say("  Checking...")
        ok, msg = Mailbox(cfg).test()
        (ui.good if ok else ui.bad)(msg)
        if ok:
            p.inbox = cfg
            if address not in p.emails:
                p.emails.append(address)
            session.save_profile()
            return True
    ui.say("  Let's leave it for now. You can try again from the menu.")
    return False


def describe_progress(session) -> list[str]:
    pr = autopilot.progress(session.db)
    if not pr["total"]:
        return []
    return [
        f"Data brokers: {pr['won']} done, {pr['waiting']} waiting for a reply, "
        f"{pr['queued']} not emailed yet (of {pr['total']}).",
    ]


def run_sweep(session) -> None:
    """Send the next batch now and process replies, with live output."""
    if not email_ready(session) and not setup_email(session):
        return
    info = list_info()
    ui.title("Emailing data brokers")
    ui.para(
        f"PrivacyWorm knows {info['count']} data brokers (from the official registry). "
        f"It emails up to {session.profile.inbox.daily_limit} a day so your account stays in "
        "good standing; autopilot sends the rest over the following days, follows up on "
        "silence, and reads the replies."
    )
    session.save_profile()
    camp = autopilot.Campaign(
        session.profile, session.db, autopilot.mailbox_for(session.profile),
        log=lambda m: ui.say(f"  {m}"),
        spacing=(1.0, 3.0),
    )
    _wrap_progress(camp)
    summary = camp.run()
    ui.say()
    ui.good(
        f"Sent {summary['sent']} new request(s) and {summary['followups'] + summary['final_notices']} follow-up(s). "
        f"{summary['done'] + summary['not_found']} broker(s) confirmed today."
    )
    pr = autopilot.progress(session.db)
    if pr["queued"]:
        days = -(-pr["queued"] // max(1, session.profile.inbox.daily_limit))
        if autopilot.is_enabled():
            ui.say(f"  {pr['queued']} still to email - autopilot will finish in about {days} day(s).")
        else:
            ui.say(f"  {pr['queued']} still to email (about {days} more day(s) at this pace).")
            offer_autopilot(session)
    if pr["todo"]:
        ui.warn(f"{pr['todo']} broker(s) need you. Choose 'To-do' from the menu.")
    ui.pause("Press Enter to go back to the menu")


def _wrap_progress(camp) -> None:
    original = camp._send

    def send(req, stage):
        label = {0: "Emailing", 1: "Following up with", 2: "Final notice to"}.get(stage, "Emailing")
        print(f"  {label} {req['broker_name'][:48]}...", end="", flush=True)
        ok = original(req, stage)
        print(ui.style(" sent" if ok else " failed", fg="green" if ok else "red"))
        return ok

    camp._send = send


def offer_autopilot(session) -> None:
    if autopilot.is_enabled():
        return
    ui.say()
    ui.para(
        "Turn on autopilot? Once a day, in the background, it sends the next batch, follows "
        "up with brokers that went quiet, clicks their confirmation links, and only bothers "
        "you when a broker insists on something only you can do. To run while you're away it "
        "keeps your passphrase in this computer's password store (Windows Credential Manager "
        "/ macOS Keychain)."
    )
    if ui.yes_no("Turn on autopilot?", default=True):
        ok, msg = autopilot.enable(session.passphrase)
        (ui.good if ok else ui.warn)(msg)
        if ok and not desktop.reminders_enabled():
            ok2, msg2 = desktop.enable_reminders()
            if not ok2:
                ui.warn(msg2)


def autopilot_menu(session) -> None:
    ui.title("Autopilot")
    on = autopilot.is_enabled()
    ui.say(f"  Autopilot is {'ON' if on else 'OFF'}.")
    last = desktop.read_schedule().get("autopilot_last_run")
    if last:
        ui.say(f"  Last run: {datetime.fromisoformat(last).astimezone().strftime('%b %d %I:%M %p')}")
    if on:
        if ui.yes_no("Turn it off? (also removes the saved passphrase)", default=False):
            autopilot.disable()
            ui.good("Autopilot is off.")
    else:
        offer_autopilot(session)


# -- To-do -------------------------------------------------------------------------


def todo_count(session) -> int:
    pr = autopilot.progress(session.db)
    return pr["todo"] + (1 if session.db.get_requests(("escalated", "refused")) else 0)


def todo(session) -> None:
    db = session.db
    items = db.get_requests("needs_you")
    stuck = db.get_requests(("escalated", "refused"))
    if not items and not stuck:
        ui.say()
        ui.good("Nothing needs you right now.")
        ui.pause()
        return
    ui.title(f"To-do: {len(items) + (1 if stuck else 0)} thing(s)")
    ui.para(
        "Each one opens in your normal web browser - not an automated one - so the "
        "'are you human' checks work like they always do."
    )
    for i, req in enumerate(items, 1):
        ui.say()
        ui.say(ui.style(f"  [{i} of {len(items)}] {req['broker_name']}", bold=True))
        ui.say(f"  {req.get('note') or 'They need something from you.'}")
        url = req.get("action_url")
        if url:
            ui.say(f"  Link: {url}")
            open_in_default_browser(url)
        ui.say(f"  If they ask for a reference, it's {req['ref']}.")
        choice = ui.choose("Done?", [
            ("d", "Done - I finished it on their site"),
            ("l", "Later"),
            ("q", "Stop for now"),
        ], default="d")
        if choice == "d":
            db.update_request(req["id"], status="ack", stage=1, note="You finished it on their site.",
                              next_action_at=autopilot._iso(autopilot.now_utc() + timedelta(days=45)))
        elif choice == "q":
            return
    if stuck:
        complaint(session, stuck)


def complaint(session, rows: list[dict]) -> None:
    ui.title(f"File one complaint about {len(rows)} broker(s)")
    ui.para(
        "These brokers ignored three requests or refused. One complaint to the Federal "
        "Trade Commission and one to your state attorney general covers all of them - "
        "PrivacyWorm wrote it for you."
    )
    text = letters.complaint(session.profile, rows)
    folder = Path.home() / "Documents" / "PrivacyWorm"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"complaint-{datetime.now().strftime('%Y-%m-%d')}.txt"
        path.write_text(text, encoding="utf-8")
        ui.say(f"  Saved the complaint text to {path}")
        open_in_default_browser(path.as_uri())
    except OSError:
        ui.say(text)
    if ui.yes_no("Open the FTC and attorney-general complaint pages now?", default=True):
        open_in_default_browser(letters.FTC_COMPLAINT_URL)
        open_in_default_browser(letters.FIND_YOUR_AG_URL)
        ui.para("Paste the complaint text into each form. Both take about 5 minutes.")
    if ui.yes_no("Mark these as complained about?", default=True):
        for r in rows:
            session.db.update_request(
                r["id"], status="complained", note="Complaint filed; will ask again in a year.",
                next_action_at=autopilot._iso(autopilot.now_utc() + timedelta(days=autopilot.RECHECK_DAYS)),
            )
        ui.good("Done. PrivacyWorm will ask them again in a year.")
    ui.pause()


def show_requests(session) -> None:
    words = {
        "queued": "not emailed yet", "sent": "asked - waiting", "ack": "they replied 'received'",
        "done": "done", "not_found": "they have nothing on you", "needs_you": "needs you",
        "refused": "refused - complaint list", "escalated": "ignored us - complaint list", "complained": "complaint filed",
    }
    rows = session.db.get_requests()
    rows = [r for r in rows if r["status"] != "queued"]
    ui.title("Data broker requests")
    if not rows:
        ui.say("  None sent yet.")
    for r in rows:
        ui.say(f"  {r['broker_name'][:40]:<40} {words.get(r['status'], r['status'])}")
    ui.pause()
