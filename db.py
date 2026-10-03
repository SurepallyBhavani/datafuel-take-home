"""SQLite tables for the sweep scraper and the /osa report."""
import sqlite3

DB_FILE = "osa.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS stores (
    store_id  TEXT PRIMARY KEY,
    city      TEXT NOT NULL,
    name      TEXT NOT NULL
);

-- one row per sweep run; as_of is UTC text like 2026-09-28T04:30:00Z
CREATE TABLE IF NOT EXISTS sweeps (
    as_of        TEXT PRIMARY KEY,
    ist_date     TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT
);

-- one row per store per sweep: the roster flags as read in that run, and how the fetch went
CREATE TABLE IF NOT EXISTS store_sweeps (
    as_of           TEXT NOT NULL REFERENCES sweeps (as_of),
    store_id        TEXT NOT NULL REFERENCES stores (store_id),
    is_active       INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    is_serviceable  INTEGER NOT NULL CHECK (is_serviceable IN (0, 1)),
    status          TEXT NOT NULL CHECK (status IN ('pending', 'complete', 'incomplete', 'skipped')),
    reason_code     TEXT CHECK (reason_code IS NULL OR reason_code IN
                        ('partial', 'soft_banned', 'fetch_failed', 'conflicting_duplicate',
                         'not_attempted', 'inactive')),
    reason_text     TEXT,
    item_count      INTEGER,
    attempts        INTEGER,   -- debugging only: requests made for this store in this sweep
    ban_recoveries  INTEGER,   -- debugging only: times a soft-ban was met and waited out
    fetched_at      TEXT,
    PRIMARY KEY (as_of, store_id)
);

-- one row per product per store per sweep; only saved for complete store-sweeps
CREATE TABLE IF NOT EXISTS observations (
    as_of        TEXT NOT NULL,
    store_id     TEXT NOT NULL,
    sku_id       TEXT NOT NULL,
    name         TEXT NOT NULL,
    in_stock     INTEGER NOT NULL CHECK (in_stock IN (0, 1)),
    qty          INTEGER,
    price        REAL,
    observed_at  TEXT,
    PRIMARY KEY (as_of, store_id, sku_id),
    FOREIGN KEY (as_of, store_id) REFERENCES store_sweeps (as_of, store_id)
);
"""


def connect(path=DB_FILE):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_tables(conn):
    conn.executescript(SCHEMA)
