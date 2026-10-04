"""End-to-end tests for the email campaign with a fake mailbox."""

import tempfile
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import pytest

from privacyworm import autopilot, letters
from privacyworm.profile import Address, InboxConfig, Name, Profile
from privacyworm.registry import Broker, parse_cppa_csv, merge
from privacyworm.state import StateDB
from privacyworm.triage import classify


def _profile(state="MO"):
    return Profile(
        name=Name(first="Simon", last="Paige"),
        addresses=[Address(street="1 Main St", city="Kansas City", state=state, zip="64113")],
        emails=["simon@example.com"],
        phones=["816-555-1234"],
        inbox=InboxConfig(user="simon@example.com", password="x", daily_limit=3),
    )


BROKERS = [
    Broker(id="alpha", name="Alpha Data", email="privacy@alpha.com", website="https://alpha.com"),
    Broker(id="bravo", name="Bravo Inc", email="old@bravo.com", website="https://bravo.com",
           extra_emails=["privacy@bravo.com"]),
    Broker(id="charlie", name="Charlie LLC", email="privacy@charlie.com", website="https://charlie.com",
           privacy_url="https://charlie.com/privacy"),
    Broker(id="delta", name="Delta Co", email="privacy@delta.com", website="https://delta.com"),
    Broker(id="echo", name="Echo Corp", email="privacy@echo.com", website="https://echo.com"),
]


class FakeMailbox:
    def __init__(self):
        self.sent = []
        self.inbox = []
        self.n = 0

    def send(self, to_addr, subject, body, in_reply_to=None):
        self.n += 1
        mid = f"<m{self.n}@example.com>"
        self.sent.append({"to": to_addr, "subject": subject, "body": body, "reply_to": in_reply_to, "id": mid})
        return mid

    def fetch_since(self, since, want=None):
        return [m for m in self.inbox if want is None or want(m)]

    def close(self):
        pass


def _reply(frm, subject, body, in_reply_to=None, mid=None):
    m = EmailMessage()
    m["From"] = frm
    m["To"] = "simon@example.com"
    m["Subject"] = subject
    m["Message-ID"] = mid or f"<r{abs(hash(body))}@x>"
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    m.set_content(body)
    return m


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    s = StateDB(db_path=path)
    yield s
    s.close()
    path.unlink(missing_ok=True)


@pytest.fixture
def clock(monkeypatch):
    t = {"now": datetime(2026, 10, 1, 15, tzinfo=timezone.utc)}
    monkeypatch.setattr(autopilot, "now_utc", lambda: t["now"])
    monkeypatch.setattr(autopilot, "all_brokers", lambda: list(BROKERS))
    return t


def _camp(db, box, clicked=None):
    return autopilot.Campaign(
        _profile(), db, box, spacing=(0, 0),
        clicker=lambda url: (clicked.append(url) if clicked is not None else None) or True,
    )


def test_full_ladder(db, clock):
    box = FakeMailbox()
    s = _camp(db, box).run()
    assert s["queued_new"] == 5 and s["sent"] == 3          # daily cap respected
    assert all("[ref PW-" in m["subject"] for m in box.sent)
    assert "Missouri" not in box.sent[0]["body"]            # no invented legal right
    assert "registered as a data broker" in box.sent[0]["body"]

    # Same day: cap already used up.
    assert _camp(db, box).run()["sent"] == 0

    # Replies arrive.
    alpha, bravo, charlie = box.sent[0], box.sent[1], box.sent[2]
    clicked = []
    box.inbox = [
        _reply("privacy@alpha.com", "Re: " + alpha["subject"], "Your data has been deleted. Thanks.",
               in_reply_to=alpha["id"]),
        _reply("MAILER-DAEMON@mail.example.com", "Delivery Status Notification (Failure)",
               f"Address not found: {bravo['to']}"),
        _reply("help@charlie.zendesk.com", "Your request " + charlie["subject"][-14:],
               "Please submit your request through our privacy portal https://charlie.com/dsr"),
    ]
    clock["now"] += timedelta(days=1)
    s = _camp(db, box, clicked).run()
    by = {r["broker_id"]: r for r in db.get_requests()}
    assert by["alpha"]["status"] == "done"
    assert by["charlie"]["status"] == "needs_you" and by["charlie"]["action_url"] == "https://charlie.com/dsr"
    # Bravo bounced -> retried at its other address in the same run.
    assert by["bravo"]["to_addr"] == "privacy@bravo.com" and by["bravo"]["status"] == "sent"
    assert {m["to"] for m in box.sent[3:]} >= {"privacy@bravo.com"}

    # Replies aren't processed twice.
    again = _camp(db, box).run()
    assert again["replies"] == 0

    # 31 days of silence from delta/echo/bravo -> follow-ups, threaded.
    clock["now"] += timedelta(days=31)
    _camp(db, box).run()
    followups = [m for m in box.sent if m["subject"].startswith("Re: ")]
    assert followups and all(m["reply_to"] for m in followups)

    # Then final notice, then the complaint list.
    clock["now"] += timedelta(days=30)
    _camp(db, box).run()
    assert any("third request" in m["body"] for m in box.sent)
    clock["now"] += timedelta(days=16)
    _camp(db, box).run()
    stuck = db.get_requests(("escalated",))
    assert stuck
    text = letters.complaint(_profile(), stuck)
    assert stuck[0]["broker_name"] in text

    # A year after alpha's win, it's asked again.
    clock["now"] += timedelta(days=366)
    _camp(db, box).run()
    alpha_row = next(r for r in db.get_requests() if r["broker_id"] == "alpha")
    assert alpha_row["cycle"] == 2


def test_verify_link_only_on_broker_domain():
    good = _reply("privacy@alpha.com", "Please confirm",
                  "Please confirm your request: https://alpha.com/verify?token=abc")
    v = classify(good, {"alpha.com"})
    assert v.kind == "verify" and v.link.startswith("https://alpha.com/verify")
    phish = _reply("privacy@alpha.com", "Please confirm",
                   "Please confirm your request: https://evil.example/verify?token=abc")
    assert classify(phish, {"alpha.com"}).kind != "verify"


@pytest.mark.parametrize("body,kind", [
    ("We were unable to locate any records matching your information.", "not_found"),
    ("This right is only available to California residents.", "refused"),
    ("We have received your request and will respond within 45 days.", "ack"),
    ("To verify your identity please send a government-issued ID.", "needs_you"),
    ("You have been added to our suppression list.", "done"),
    ("Hmm, interesting question about llamas.", "needs_you"),
])
def test_classify(body, kind):
    assert classify(_reply("a@alpha.com", "Re: x", body), {"alpha.com"}).kind == kind


def test_quoted_letter_does_not_fool_classifier():
    body = "Thanks.\n\nOn Mon, Simon wrote:\n> Please delete ... has been deleted"
    assert classify(_reply("a@alpha.com", "Re: x", body), {"alpha.com"}).kind == "needs_you"


def test_state_law_cited_only_where_it_exists():
    assert "Texas Data Privacy" in letters.initial(_profile("TX"), "X", "PW-AAAAAA")
    assert "under " not in letters.initial(_profile("MO"), "X", "PW-AAAAAA").split("Specifically")[0]
    assert "Date of birth" not in letters.initial(_profile(), "X", "PW-AAAAAA")


def test_registry_parse_and_merge():
    csv_text = (
        "Data broker name:,Data broker primary website:,Data broker primary contact email address:\n"
        "Acme Data,https://acme.com,info@acme.com; privacy@acme.com\n"
        "Acme Data Again,www.acme.com,other@acme.com\n"
        "No Email Co,https://none.com,\n"
    )
    old = "Data Broker Name,Email Address,Website URL\nBeta,privacy [at] beta.io,http://beta.io\n"
    merged = merge([parse_cppa_csv(csv_text), parse_cppa_csv(old)])
    assert [b.name for b in merged] == ["Acme Data", "Beta"]
    acme = merged[0]
    assert acme.email == "privacy@acme.com" and acme.extra_emails == ["info@acme.com"]
    assert merged[1].email == "privacy@beta.io"


def test_bundled_registry_is_big():
    from privacyworm.registry import load_brokers

    assert len(load_brokers()) > 500
