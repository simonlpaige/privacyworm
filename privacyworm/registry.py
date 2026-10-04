"""The broker list for email deletion requests.

Hand-written playbooks only cover a few people-search sites. To reach
everyone, PrivacyWorm also uses the public data-broker registry run by
California's privacy agency (CPPA). Every company that sells data about
Californians must register there with a privacy contact address - which
in practice is nearly every US data broker, wherever *you* live.

The list ships with PrivacyWorm (``privacyworm/data/brokers.json``) and
``privacyworm registry update`` refreshes it from the source. Downloading
the public list sends nothing about you.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import tldextract

from privacyworm.config import get_config_dir

BUNDLED_PATH = Path(__file__).parent / "data" / "brokers.json"
CPPA_BASE = "https://cppa.ca.gov/data_broker_registry/"
CPPA_SOURCES = (
    # newest first: when the same company shows up twice, the newer row wins
    "registry.csv",
    "complete-reg-data-brokers.csv",
)

_EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"(https?://[^\s;,<>\"]+|www\.[^\s;,<>\"]+)", re.I)

# Mailboxes nobody reads - we prefer anything else the row offers.
_GENERIC_LOCAL = {"info", "sales", "support", "hello", "contact", "accounting", "marketing", "admin"}


@dataclass
class Broker:
    id: str
    name: str
    email: str
    website: str = ""
    privacy_url: str = ""
    fcra: bool = False
    source: str = "cppa"
    extra_emails: list[str] = field(default_factory=list)

    @property
    def domain(self) -> str:
        return registered_domain(self.website or self.email.split("@")[-1])

    def domains(self) -> set[str]:
        """Every domain mail from this broker might come from."""
        out = {self.domain, registered_domain(self.email.split("@")[-1])}
        out.update(registered_domain(e.split("@")[-1]) for e in self.extra_emails)
        return {d for d in out if d}


def registered_domain(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    ext = tldextract.extract(value)
    return f"{ext.domain}.{ext.suffix}".lower() if ext.suffix else ext.domain.lower()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:60] or "broker"


def _clean_email(raw: str) -> list[str]:
    raw = (raw or "").replace(" [at] ", "@").replace("[at]", "@").replace(" [dot] ", ".")
    found = []
    for m in _EMAIL.findall(raw):
        e = m.strip().strip(".").lower()
        if e not in found:
            found.append(e)
    return found


def _first_url(raw: str) -> str:
    m = _URL.search(raw or "")
    if not m:
        return ""
    url = m.group(1).rstrip(".)")
    return url if url.startswith("http") else "https://" + url


def _pick(row: dict, *needles: str) -> str:
    for key, value in row.items():
        k = (key or "").lower()
        if all(n in k for n in needles):
            return value or ""
    return ""


def parse_cppa_csv(text: str) -> list[Broker]:
    """Parse either CPPA CSV layout (the current registry or the history file)."""
    out: list[Broker] = []
    for row in csv.DictReader(io.StringIO(text)):
        name = (_pick(row, "data broker name") or _pick(row, "broker name")).strip()
        if not name:
            continue
        emails = _clean_email(_pick(row, "email"))
        if not emails:
            continue
        # Prefer a privacy-looking mailbox over sales@ / info@.
        emails.sort(key=lambda e: e.split("@")[0] in _GENERIC_LOCAL)
        website = _first_url(_pick(row, "primary website")) or _first_url(_pick(row, "website url"))
        privacy = _first_url(_pick(row, "exercise")) or _first_url(_pick(row, "opt out"))
        fcra = _pick(row, "regulated by the federal fair credit").strip().lower().startswith("y")
        out.append(Broker(
            id=_slug(name),
            name=name,
            email=emails[0],
            extra_emails=emails[1:],
            website=website,
            privacy_url=privacy,
            fcra=fcra,
        ))
    return out


def merge(lists: list[list[Broker]]) -> list[Broker]:
    """Merge lists, earliest list wins, de-duplicated by domain and address."""
    seen_domains: set[str] = set()
    seen_emails: set[str] = set()
    seen_ids: set[str] = set()
    merged: list[Broker] = []
    for brokers in lists:
        for b in brokers:
            key = b.domain
            if b.email in seen_emails or (key and key in seen_domains):
                continue
            base, n = b.id, 2
            while b.id in seen_ids:
                b.id = f"{base}-{n}"
                n += 1
            seen_ids.add(b.id)
            seen_emails.add(b.email)
            if key:
                seen_domains.add(key)
            merged.append(b)
    merged.sort(key=lambda b: b.name.lower())
    return merged


def _override_path() -> Path:
    return get_config_dir() / "brokers.json"


def _read(path: Path) -> list[Broker]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Broker(**b) for b in data["brokers"]]


def load_brokers() -> list[Broker]:
    """The freshest broker list available: downloaded update, else bundled."""
    for path in (_override_path(), BUNDLED_PATH):
        try:
            if path.exists():
                return _read(path)
        except (OSError, ValueError, TypeError):
            continue
    return []


def list_info() -> dict:
    for path in (_override_path(), BUNDLED_PATH):
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return {"path": str(path), "updated": data.get("updated"), "count": len(data["brokers"])}
            except (OSError, ValueError, KeyError):
                continue
    return {"path": None, "updated": None, "count": 0}


def save(brokers: list[Broker], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "California Privacy Protection Agency data broker registry (" + CPPA_BASE + ")",
        "updated": datetime.now(timezone.utc).date().isoformat(),
        "brokers": [asdict(b) for b in brokers],
    }
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def download() -> list[Broker]:
    """Fetch and merge the current CPPA registry files."""
    import requests

    lists = []
    for name in CPPA_SOURCES:
        resp = requests.get(
            CPPA_BASE + name,
            timeout=60,
            headers={"User-Agent": "privacyworm (open-source opt-out tool)"},
        )
        resp.raise_for_status()
        lists.append(parse_cppa_csv(resp.content.decode("utf-8-sig", errors="replace")))
    return merge(lists)


def update() -> int:
    """Download the registry into the config folder. Returns broker count."""
    brokers = download()
    if len(brokers) < 100:
        raise RuntimeError(f"Registry download looks wrong (only {len(brokers)} brokers); kept the old list.")
    save(brokers, _override_path())
    return len(brokers)
