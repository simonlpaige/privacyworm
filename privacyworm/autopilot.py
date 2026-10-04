"""Autopilot: the hands-off deletion campaign.

Each run (daily, from the OS scheduler, or on demand):

  1. Make sure every broker in the registry has a request queued.
  2. Read new replies and act on them (see ``triage``): mark wins, click
     confirmation links on the broker's own domain, retry a bounced
     request at the broker's other address, queue to-dos for the rest.
  3. Follow up on silence: a reminder at 30 days, a final notice at 60,
     and at 75 days the broker goes on the complaint list.
  4. Send the next batch of new requests, under a daily cap.
  5. A year after a broker confirms, ask again - brokers re-collect.

Nothing here needs a browser, so there are no CAPTCHAs to fight. The
only things that ever reach you are on the to-do list: brokers that
insist on their own web form or ID, and replies the rules can't read.
"""

from __future__ import annotations

import logging
import random
import secrets
import string
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Callable

from privacyworm import letters, triage
from privacyworm.mailer import Mailbox
from privacyworm.playbook import load_all_playbooks
from privacyworm.profile import Profile
from privacyworm.registry import Broker, load_brokers, registered_domain
from privacyworm.state import StateDB

logger = logging.getLogger("privacyworm")

FOLLOW_UP_DAYS = 30
FINAL_NOTICE_DAYS = 60
ESCALATE_DAYS = 75
RECHECK_DAYS = 365

# Statuses
WAITING = ("sent", "ack")          # asked, no outcome yet
WON = ("done", "not_found")        # finished for this cycle
TODO = ("needs_you",)              # a human has to do something
STUCK = ("escalated", "refused")   # goes on the complaint list
COMPLAINED = ("complained",)       # complaint filed; ask again next year


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def new_ref() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "PW-" + "".join(secrets.choice(alphabet) for _ in range(6))


def all_brokers() -> list[Broker]:
    """Registry brokers plus any email-only playbook brokers it doesn't list."""
    brokers = load_brokers()
    known = {b.domain for b in brokers}
    for pb in load_all_playbooks():
        if pb.opt_out.method == "email" and pb.opt_out.email_address:
            dom = registered_domain(pb.homepage)
            if dom not in known:
                brokers.append(Broker(
                    id=pb.broker, name=pb.display_name, email=pb.opt_out.email_address,
                    website=pb.homepage, source="playbook",
                ))
    return brokers


def sync_queue(db: StateDB, brokers: list[Broker] | None = None) -> int:
    """Queue a request for every broker that doesn't have one yet."""
    added = 0
    for b in brokers if brokers is not None else all_brokers():
        if db.ensure_request(b.id, b.name, b.email, new_ref()):
            added += 1
    return added


class Campaign:
    def __init__(
        self,
        profile: Profile,
        db: StateDB,
        mailbox: Mailbox | None,
        *,
        dry_run: bool = False,
        spacing: tuple[float, float] = (4.0, 9.0),
        log: Callable[[str], None] = lambda m: None,
        clicker: Callable[[str], bool] | None = None,
    ):
        self.profile = profile
        self.db = db
        self.mailbox = mailbox
        self.dry_run = dry_run
        self.spacing = spacing
        self.log = log
        self.clicker = clicker or click_link
        self.brokers = {b.id: b for b in all_brokers()}
        self.summary = {
            "queued_new": 0, "sent": 0, "followups": 0, "final_notices": 0, "escalated": 0,
            "replies": 0, "done": 0, "not_found": 0, "clicked": 0, "todo_new": 0,
            "refused": 0, "bounced": 0, "rechecks": 0, "errors": 0,
        }

    # -- helpers ----------------------------------------------------------------

    def _limit(self) -> int:
        if self.profile.inbox is None:
            return 0
        return max(0, int(self.profile.inbox.daily_limit))

    def _sent_today(self) -> int:
        midnight = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.db.sent_since(_iso(midnight))

    def _pause(self) -> None:
        if not self.dry_run and self.spacing[1] > 0:
            time.sleep(random.uniform(*self.spacing))  # nosec B311 - pacing, not crypto

    def _send(self, req: dict, stage: int) -> bool:
        p = self.profile
        first = _parse(req.get("first_sent_at"))
        days = (now_utc() - first).days if first else 0
        if stage == 0:
            body = letters.initial(p, req["broker_name"], req["ref"])
        elif stage == 1:
            body = letters.follow_up(p, req["broker_name"], req["ref"], days)
        else:
            body = letters.final_notice(p, req["broker_name"], req["ref"], days)
        subject = letters.subject(p, req["ref"], stage)
        if self.dry_run:
            self.log(f"[dry run] would email {req['broker_name']} <{req['to_addr']}> ({subject})")
            return True
        assert self.mailbox is not None  # nosec B101 - run() checks this
        try:
            msg_id = self.mailbox.send(req["to_addr"], subject, body, in_reply_to=req["message_ids"] or None)
        except Exception as e:  # noqa: BLE001 - one bad address mustn't stop the run
            self.summary["errors"] += 1
            self.log(f"Couldn't email {req['broker_name']}: {e}")
            return False
        now = now_utc()
        self.db.update_request(
            req["id"],
            stage=stage,
            status="sent",
            first_sent_at=req.get("first_sent_at") or _iso(now),
            last_sent_at=_iso(now),
            message_ids=req["message_ids"] + [msg_id],
            next_action_at=_iso(self._next_after(stage, first or now)),
        )
        return True

    @staticmethod
    def _next_after(stage: int, first: datetime) -> datetime:
        return first + timedelta(days={0: FOLLOW_UP_DAYS, 1: FINAL_NOTICE_DAYS}.get(stage, ESCALATE_DAYS))

    # -- steps --------------------------------------------------------------------

    def triage_inbox(self, since: datetime) -> None:
        if self.mailbox is None:
            return
        requests_ = self.db.get_requests()
        by_ref = {r["ref"]: r for r in requests_}
        by_msgid = {m: r for r in requests_ for m in r["message_ids"]}
        by_domain: dict[str, dict] = {}
        shared: set[str] = set()
        for r in requests_:
            b = self.brokers.get(r["broker_id"])
            for d in (b.domains() if b else {registered_domain(r["to_addr"].split("@")[-1])}):
                if d in by_domain and by_domain[d]["id"] != r["id"]:
                    shared.add(d)  # e.g. 11 TransUnion companies: only threading can tell them apart
                by_domain.setdefault(d, r)
        for d in shared:
            by_domain.pop(d, None)

        own = registered_domain(self.profile.inbox.user.split("@")[-1]) if self.profile.inbox else ""

        def match(msg) -> dict | None:
            for msg_ref in triage.references(msg):
                if msg_ref in by_msgid:
                    return by_msgid[msg_ref]
            tag = triage.find_ref(msg)
            if tag and tag in by_ref:
                return by_ref[tag]
            dom = triage.sender_domain(msg)
            if dom and dom != own and dom in by_domain:
                return by_domain[dom]
            return None

        def wanted(head) -> bool:
            if triage.REF_RE.search(str(head.get("Subject", ""))):
                return True
            if triage.references(head) & by_msgid.keys():
                return True
            dom = triage.sender_domain(head)
            sender = str(head.get("From", "")).lower()
            return (dom in by_domain and dom != own) or any(b in sender for b in triage.BOUNCE_SENDERS)

        try:
            messages = self.mailbox.fetch_since(since, want=wanted)
        except Exception as e:  # noqa: BLE001
            self.summary["errors"] += 1
            self.log(f"Couldn't read the inbox: {e}")
            return

        for msg in messages:
            mid = str(msg.get("Message-ID", "")).strip()
            req = match(msg)
            if req is None and any(b in str(msg.get("From", "")).lower() for b in triage.BOUNCE_SENDERS):
                body = triage.body_text(msg)
                req = next((r for r in requests_ if r["to_addr"] in body or r["ref"] in body), None)
            if req is None or not mid:
                continue
            if self.db.email_already_processed(req["broker_id"], mid):
                continue
            self.summary["replies"] += 1
            broker = self.brokers.get(req["broker_id"])
            domains = broker.domains() if broker else {registered_domain(req["to_addr"].split("@")[-1])}
            self._apply(req, triage.classify(msg, domains), broker)
            if not self.dry_run:
                self.db.mark_email_processed(req["broker_id"], mid)

    def _apply(self, req: dict, v: triage.Verdict, broker: Broker | None) -> None:
        upd = self.db.update_request if not self.dry_run else (lambda *a, **k: None)
        name = req["broker_name"]
        if v.kind in WON:
            upd(req["id"], status=v.kind, note=v.note, next_action_at=_iso(now_utc() + timedelta(days=RECHECK_DAYS)))
            self.summary[v.kind] += 1
            self.log(f"{name}: {v.note}")
        elif v.kind == "verify" and v.link:
            if not self.dry_run and self.clicker(v.link):
                upd(req["id"], status="ack", note="Confirmation link clicked.")
                self.summary["clicked"] += 1
                self.log(f"{name}: clicked their confirmation link.")
            else:
                upd(req["id"], status="needs_you", note="Click their confirmation link.", action_url=v.link)
                self.summary["todo_new"] += 1
        elif v.kind == "bounced":
            spare = [e for e in (broker.extra_emails if broker else []) if e != req["to_addr"]]
            if spare:
                upd(req["id"], status="queued", stage=0, to_addr=spare[0], message_ids=[],
                    note=f"First address bounced; retrying {spare[0]}.")
                self.log(f"{name}: address bounced, will retry at {spare[0]}.")
            else:
                url = (broker.privacy_url or broker.website) if broker else None
                upd(req["id"], status="needs_you", note="Their email bounces. Use their website instead.", action_url=url)
                self.summary["todo_new"] += 1
            self.summary["bounced"] += 1
        elif v.kind == "refused":
            upd(req["id"], status="refused", note=v.note)
            self.summary["refused"] += 1
            self.log(f"{name}: {v.note}")
        elif v.kind == "ack":
            if req["status"] in ("sent", "queued"):
                upd(req["id"], status="ack", note=v.note)
        else:  # needs_you
            url = v.link or ((broker.privacy_url or broker.website) if broker else None)
            upd(req["id"], status="needs_you", note=v.note, action_url=url)
            self.summary["todo_new"] += 1
            self.log(f"{name}: needs you - {v.note}")

    def follow_ups(self, budget: int) -> int:
        """Send due reminders / final notices; escalate the silent. Returns emails sent."""
        sent = 0
        now = now_utc()
        for req in self.db.get_requests(WAITING):
            due = _parse(req.get("next_action_at"))
            if not due or due > now:
                continue
            stage = int(req["stage"])
            if stage >= 2:
                if not self.dry_run:
                    self.db.update_request(req["id"], status="escalated", stage=3,
                                           note="No answer after three requests.")
                self.summary["escalated"] += 1
                continue
            if sent >= budget:
                continue
            if self._send(req, stage + 1):
                sent += 1
                self.summary["followups" if stage == 0 else "final_notices"] += 1
                self._pause()
        return sent

    def rechecks(self) -> None:
        """A year after a win, ask again (brokers re-collect)."""
        now = now_utc()
        for req in self.db.get_requests(WON + COMPLAINED):
            due = _parse(req.get("next_action_at"))
            if due and due <= now and not self.dry_run:
                self.db.update_request(req["id"], status="queued", stage=0, message_ids=[],
                                       first_sent_at=None, cycle=int(req["cycle"]) + 1,
                                       note="Yearly re-check.")
                self.summary["rechecks"] += 1

    def send_new(self, budget: int) -> int:
        sent = 0
        queued = sorted(self.db.get_requests("queued"), key=lambda r: priority(self.brokers.get(r["broker_id"]), r))
        for req in queued:
            if sent >= budget:
                break
            if self._send(req, 0):
                sent += 1
                self.summary["sent"] += 1
                self._pause()
        return sent

    def run(self, inbox_since: datetime | None = None) -> dict:
        if self.mailbox is None and not self.dry_run:
            raise RuntimeError("Email isn't set up yet.")
        self.summary["queued_new"] = sync_queue(self.db, list(self.brokers.values()))
        since = inbox_since or now_utc() - timedelta(days=14)
        self.triage_inbox(since)
        budget = max(0, self._limit() - self._sent_today()) if not self.dry_run else self._limit()
        budget -= self.follow_ups(budget)
        self.rechecks()
        self.send_new(max(0, budget))
        if self.mailbox is not None:
            self.mailbox.close()
        return self.summary


# Sites that publish people's profiles (and the biggest data wholesalers)
# go first: they're what strangers actually find when they search you.
PRIORITY_WORDS = (
    "people", "search", "background", "lookup", "phone", "record", "spokeo", "whitepages",
    "intelius", "radaris", "mylife", "truthfinder", "checkmate", "beenverified", "ltvco",
    "peopleconnect", "nuwber", "usphonebook", "clustrmaps", "thatsthem", "spydialer",
    "zabasearch", "addresses", "familytree", "peekyou", "pipl", "neighbor", "voter",
    "acxiom", "lexisnexis", "epsilon", "experian", "equifax", "transunion", "oracle",
    "zoominfo", "verisk", "corelogic", "infutor", "data axle", "dataaxle",
)


@lru_cache(maxsize=1)
def _playbook_domains() -> frozenset[str]:
    return frozenset(registered_domain(pb.homepage) for pb in load_all_playbooks())


def priority(broker: Broker | None, req: dict) -> tuple[int, str]:
    text = f"{req['broker_name']} {req['to_addr']} {broker.website if broker else ''}".lower()
    if broker is not None and broker.domain in _playbook_domains():
        return (0, req["broker_name"].lower())
    if any(w in text for w in PRIORITY_WORDS):
        return (1, req["broker_name"].lower())
    return (2, req["broker_name"].lower())


def click_link(url: str) -> bool:
    """Open a confirmation link without a browser. True if it worked."""
    import requests

    from privacyworm.brokers.base import log_network_request

    log_network_request("GET", url, "confirmation link (autopilot)")
    try:
        resp = requests.get(
            url,
            timeout=30,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; privacyworm confirmation)"},
        )
    except requests.RequestException:
        return False
    text = resp.text[:5000].lower()
    blocked = any(m in text for m in ("captcha", "verify you are human", "just a moment"))
    return resp.status_code < 400 and not blocked


def progress(db: StateDB) -> dict[str, int]:
    """Counts for the home screen."""
    c = db.request_counts()
    return {
        "total": sum(c.values()),
        "queued": c.get("queued", 0),
        "waiting": sum(c.get(s, 0) for s in WAITING),
        "won": sum(c.get(s, 0) for s in WON),
        "todo": sum(c.get(s, 0) for s in TODO),
        "stuck": sum(c.get(s, 0) for s in STUCK),
        "complained": c.get("complained", 0),
    }


# -- Running unattended ---------------------------------------------------------


def _marker():
    from privacyworm.config import get_config_dir

    return get_config_dir() / ".autopilot"


def is_enabled() -> bool:
    return _marker().exists()


def enable(passphrase: str) -> tuple[bool, str]:
    from privacyworm import vault

    if not vault.save(passphrase):
        return False, (
            "Couldn't store the passphrase in this computer's keychain, so autopilot "
            "can't run while you're away. You can still run it by hand."
        )
    _marker().write_text("on\n", encoding="utf-8")
    return True, "Autopilot is on. It runs once a day in the background."


def disable() -> None:
    from privacyworm import vault

    vault.forget()
    _marker().unlink(missing_ok=True)


def _log_line(text: str) -> None:
    from privacyworm.config import get_config_dir

    path = get_config_dir() / "autopilot.log"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{now_utc().isoformat(timespec='seconds')} {text}\n")
    except OSError:
        pass


def mailbox_for(profile: Profile) -> Mailbox | None:
    if profile.inbox is None or not (profile.inbox.password or profile.inbox.user):
        return None
    from privacyworm.letters import full_name

    return Mailbox(profile.inbox, display_name=full_name(profile))


def run_unattended() -> dict | None:
    """Called by the daily scheduler. Returns the summary, or None if it couldn't run."""
    from privacyworm import desktop, vault
    from privacyworm.config import get_profile_path, is_state_encryption_enabled
    from privacyworm.profile import decrypt_profile

    if not is_enabled():
        return None
    passphrase = vault.load()
    if not passphrase:
        _log_line("skipped: passphrase not in keychain")
        return None
    try:
        profile = decrypt_profile(passphrase, get_profile_path(encrypted=True))
    except Exception:  # noqa: BLE001
        _log_line("skipped: stored passphrase no longer unlocks the profile")
        return None
    mailbox = mailbox_for(profile)
    if mailbox is None:
        _log_line("skipped: email not set up")
        return None
    from privacyworm.config import get_config_dir

    lock = get_config_dir() / ".state.lock"
    if lock.exists():
        try:
            started = _parse(lock.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            started = None
        if started and now_utc() - started < timedelta(hours=6):
            _log_line("skipped: PrivacyWorm is open right now")
            return None
    _refresh_registry_if_stale()
    db = StateDB(passphrase=passphrase) if is_state_encryption_enabled() else StateDB()
    try:
        sched = desktop.read_schedule()
        last = _parse(sched.get("autopilot_last_run"))
        since = (last - timedelta(days=2)) if last else None
        summary = Campaign(profile, db, mailbox, log=_log_line).run(inbox_since=since)
        sched = desktop.read_schedule()
        sched["autopilot_last_run"] = now_utc().isoformat()
        p = progress(db)
        sched["todo"] = p["todo"] + (1 if p["stuck"] else 0)
        desktop.write_schedule(sched)
        _log_line("run: " + ", ".join(f"{k}={v}" for k, v in summary.items() if v))
        summary["progress"] = p
        return summary
    finally:
        db.close()


def _refresh_registry_if_stale(max_age_days: int = 30) -> None:
    """Pick up newly registered brokers about once a month (public list, no personal data sent)."""
    from privacyworm.registry import list_info, update

    updated = list_info().get("updated")
    try:
        age = (now_utc().date() - datetime.fromisoformat(updated).date()).days if updated else 999
    except ValueError:
        age = 999
    if age < max_age_days:
        return
    try:
        n = update()
        _log_line(f"registry refreshed: {n} brokers")
    except Exception as e:  # noqa: BLE001 - keep using the list we have
        _log_line(f"registry refresh failed: {e}")
