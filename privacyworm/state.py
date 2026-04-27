"""SQLite-backed state: listings found, opt-outs filed, rescan schedule.

We store the listing URL but not the full scraped text. The broker name and
listing URL are the minimum needed to file an opt-out and track status. The
scoring columns (confidence, match_score, matched_fields) hold the verdict
of the matching engine so we can show it back at confirm time without
keeping raw scraped HTML around.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from privacyworm.config import get_state_db_path

logger = logging.getLogger("privacyworm")

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,
    listing_url TEXT,
    found_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'found',
    confidence TEXT,
    match_score INTEGER,
    matched_fields TEXT,
    UNIQUE (broker, listing_url)
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
        self._migrate_listings_schema()

    def _migrate_listings_schema(self) -> None:
        """Bring the listings table to the current shape.

        Three migrations roll up into one rebuild so older databases land in
        the same place as a fresh install:

        - Add UNIQUE(broker, listing_url) where it is missing.
        - Drop the PII columns (matched_name, matched_city, matched_state,
          raw_snippet) from databases that still have them. We never need
          scraped text after the listing has been scored, and keeping it on
          disk is a privacy footgun.
        - Add the scoring columns (confidence, match_score, matched_fields)
          where they don't exist yet.

        On a fresh database the SCHEMA above already matches, so this exits
        early without touching anything.
        """
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='listings'"
        ).fetchone()
        if row is None:
            return

        cols_info = self.conn.execute("PRAGMA table_info(listings)").fetchall()
        existing_cols = {c[1] for c in cols_info}
        pii_cols = {"matched_name", "matched_city", "matched_state", "raw_snippet"}

        has_pii = bool(pii_cols & existing_cols)
        has_unique = "UNIQUE" in (row[0] or "")
        new_cols = {"confidence", "match_score", "matched_fields"}
        missing_new_cols = new_cols - existing_cols

        if not has_pii and has_unique and not missing_new_cols:
            return

        logger.info("Migrating listings table: drop PII columns, add scoring columns, ensure UNIQUE")

        # Remove duplicate non-null listing_url rows, keeping the highest id per pair.
        self.conn.execute("""
            DELETE FROM listings
            WHERE listing_url IS NOT NULL
              AND id NOT IN (
                  SELECT MAX(id) FROM listings
                  WHERE listing_url IS NOT NULL
                  GROUP BY broker, listing_url
              )
        """)

        self.conn.execute("DROP TABLE IF EXISTS listings_new")
        self.conn.execute("""
            CREATE TABLE listings_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broker TEXT NOT NULL,
                listing_url TEXT,
                found_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'found',
                confidence TEXT,
                match_score INTEGER,
                matched_fields TEXT,
                UNIQUE (broker, listing_url)
            )
        """)

        select_confidence = "confidence" if "confidence" in existing_cols else "NULL"
        select_match_score = "match_score" if "match_score" in existing_cols else "NULL"
        select_matched_fields = "matched_fields" if "matched_fields" in existing_cols else "NULL"

        self.conn.execute(f"""
            INSERT INTO listings_new
                (id, broker, listing_url, found_at, status, confidence, match_score, matched_fields)
            SELECT id, broker, listing_url, found_at, status,
                   {select_confidence}, {select_match_score}, {select_matched_fields}
            FROM listings
        """)
        self.conn.execute("DROP TABLE listings")
        self.conn.execute("ALTER TABLE listings_new RENAME TO listings")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- Listings --

    def add_listing(
        self,
        broker: str,
        listing_url: str | None = None,
        confidence: str | None = None,
        match_score: int | None = None,
        matched_fields: list[str] | None = None,
    ) -> int:
        fields_json = json.dumps(matched_fields) if matched_fields is not None else None
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO listings "
            "(broker, listing_url, found_at, confidence, match_score, matched_fields) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (broker, listing_url, self._now(), confidence, match_score, fields_json),
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
