"""Mailbox send/read against fake SMTP and IMAP servers."""

from datetime import datetime, timezone
from email.message import EmailMessage

from privacyworm import mailer
from privacyworm.profile import InboxConfig


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.sent, self.tls, self.auth = host, port, [], False, None
        FakeSMTP.instances.append(self)

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, pw):
        self.auth = (user, pw)

    def send_message(self, msg):
        self.sent.append(msg)

    def quit(self):
        pass


def _raw(frm, subject, body, mid):
    m = EmailMessage()
    m["From"], m["Subject"], m["Message-ID"] = frm, subject, mid
    m.set_content(body)
    return m.as_bytes()


class FakeIMAP:
    def __init__(self, host, port, timeout=None):
        self.msgs = {
            b"1": _raw("friend@gmail.com", "lunch?", "hi", "<1@x>"),
            b"2": _raw("privacy@alpha.com", "Re: Request [ref PW-ABC123]", "deleted", "<2@x>"),
        }
        self.fetched_full = []

    def login(self, u, p):
        pass

    def select(self, box, readonly=False):
        assert readonly
        return "OK", [b"2"]

    def search(self, charset, query):
        return "OK", [b"1 2"]

    def fetch(self, nums, spec):
        out = []
        for n in nums.split(","):
            raw = self.msgs[n.encode()]
            if "HEADER.FIELDS" in spec:
                raw = raw.split(b"\n\n")[0] + b"\n\n"
            else:
                self.fetched_full.append(n)
            out += [(n.encode() + b" (BODY[] {1}", raw), b")"]
        return "OK", out

    def logout(self):
        pass


def test_send_threads_and_uses_starttls(monkeypatch):
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    box = mailer.Mailbox(InboxConfig(user="simon@gmail.com", password="app pw"), display_name="Simon Paige")
    mid = box.send("privacy@alpha.com", "Re: hi", "body", in_reply_to=["<a@x>", "<b@x>"])
    smtp = FakeSMTP.instances[-1]
    assert (smtp.host, smtp.port, smtp.tls) == ("smtp.gmail.com", 587, True)
    msg = smtp.sent[0]
    assert msg["Message-ID"] == mid and msg["In-Reply-To"] == "<b@x>"
    assert msg["References"] == "<a@x> <b@x>"
    assert "Simon Paige" in msg["From"]


def test_fetch_downloads_bodies_only_for_wanted(monkeypatch):
    fake = {}

    def factory(host, port, timeout=None):
        fake["imap"] = FakeIMAP(host, port)
        return fake["imap"]

    monkeypatch.setattr(mailer.imaplib, "IMAP4_SSL", factory)
    box = mailer.Mailbox(InboxConfig(user="simon@gmail.com", password="x"))
    msgs = box.fetch_since(datetime(2026, 10, 1, tzinfo=timezone.utc),
                           want=lambda h: "PW-" in str(h["Subject"]))
    assert [str(m["Message-ID"]) for m in msgs] == ["<2@x>"]
    assert fake["imap"].fetched_full == ["2"]


def test_provider_presets():
    assert mailer.provider_for("a@gmail.com")[1] == "smtp.gmail.com"
    assert mailer.provider_for("a@example.org")[:3] == ("imap.example.org", "smtp.example.org", 587)
