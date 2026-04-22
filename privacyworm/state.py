"""SQLite-backed state: listings found, opt-outs filed, rescan schedule."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from privacyworm.config import get_state_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,
    listing_url TEXT,
    matched_name TEXT,
    matched_city TEXT,
    matched_state TEXT,
    raw_snippet TEXT,
    found_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'found'
);

CREATE TABLE IF NOT EXISTS optouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    method TEXT NOT NULL,
    filed_at TEXT NOT NULL,
    confirmation_received_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    details TEXT
);

CREATE TABLE IF NOT EXISTS rescans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,
    last_scanned_at TEXT NOT NULL,
    next_scan_at TEXT NOT NULL
);
"""

VALID_LISTING_STATUSES = {"found", "opt_out_filed", "opt_out_confirmed", "removed", "re_listed"}
VALID_OPTOUT_STATUSES = {"pending", "confirmed", "failed", "expired"}


class StateDB:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or get_state_db_path()
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- Listings --

    def add_listing(
        self,
        broker: str,
        listing_url: str | None = None,
        matched_name: str | None = None,
        matched_city: str | None = None,
        matched_state: str | None = None,
        raw_snippet: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO listings (broker, listing_url, matched_name, matched_city, matched_state, raw_snippet, found_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (broker, listing_url, matched_name, matched_city, matched_state, raw_snippet, self._now()),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_listings(self, broker: Optional[str] = None, status: Optional[str] = None) -> list[dict]:
        query = "SELECT * FROM listings WHERE 1=1"
        params: list = []
        if broker:
            query += " AND broker = ?"
            params.append(broker)
        if status:
            query += " AND status = ?"
            params.append(status)
        rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def update_listing_status(self, listing_id: int, status: str) -> None:
        if status not in VALID_LISTING_STATUSES:
            raise ValueError(f"Invalid listing status: {status}")
        self.conn.execute("UPDATE listings SET status = ? WHERE id = ?", (status, listing_id))
        self.conn.commit()

    # -- Opt-outs --

    def add_optout(self, listing_id: int, method: str, details: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO optouts (listing_id, method, filed_at, details) VALUES (?, ?, ?, ?)",
            (listing_id, method, self._now(), details),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_optouts(self, status: Optional[str] = None) -> list[dict]:
        query = "SELECT * FROM optouts WHERE 1=1"
        params: list = []
        if status:
            query += " AND status = ?"
            params.append(status)
        rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def confirm_optout(self, optout_id: int) -> None:
        self.conn.execute(
            "UPDATE optouts SET status = 'confirmed', confirmation_received_at = ? WHERE id = ?",
            (self._now(), optout_id),
        )
        self.conn.commit()

    def fail_optout(self, optout_id: int, details: str | None = None) -> None:
        self.conn.execute(
            "UPDATE optouts SET status = 'failed', details = ? WHERE id = ?",
            (details, optout_id),
        )
        self.conn.commit()

    # -- Rescans --

    def set_rescan(self, broker: str, next_scan_at: str) -> None:
        existing = self.conn.execute("SELECT id FROM rescans WHERE broker = ?", (broker,)).fetchone()
        if existing:
            self.conn.execute(
                "UPDATE rescans SET last_scanned_at = ?, next_scan_at = ? WHERE broker = ?",
                (self._now(), next_scan_at, broker),
            )
        else:
            self.conn.execute(
                "INSERT INTO rescans (broker, last_scanned_at, next_scan_at) VALUES (?, ?, ?)",
                (broker, self._now(), next_scan_at),
            )
        self.conn.commit()

    def get_due_rescans(self) -> list[dict]:
        now = self._now()
        rows = self.conn.execute(
            "SELECT * FROM rescans WHERE next_scan_at <= ?", (now,)
        ).fetchall()
        return [dict(row) for row in rows]

    # -- Summary --

    def summary(self) -> dict:
        listings = self.conn.execute("SELECT COUNT(*) as n FROM listings").fetchone()
        pending = self.conn.execute(
            "SELECT COUNT(*) as n FROM optouts WHERE status = 'pending'"
        ).fetchone()
        confirmed = self.conn.execute(
            "SELECT COUNT(*) as n FROM optouts WHERE status = 'confirmed'"
        ).fetchone()
        return {
            "total_listings": listings["n"],
            "pending_optouts": pending["n"],
            "confirmed_optouts": confirmed["n"],
        }
