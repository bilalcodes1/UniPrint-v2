import sqlite3
import json
from contextlib import contextmanager


def get_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


@contextmanager
def db_cursor(db_path):
    conn = get_db(db_path)
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path):
    conn = get_db(db_path)
    cur = conn.cursor()

    cur.executescript('''
        CREATE TABLE IF NOT EXISTS students (
            national_id_hash    TEXT PRIMARY KEY,
            name                TEXT,
            department          TEXT,
            stage               TEXT,
            preferences         TEXT DEFAULT '{}',
            total_prints        INTEGER DEFAULT 0,
            device_fingerprint  TEXT,
            last_seen           TEXT,
            created_at          TEXT DEFAULT (datetime('now')),
            updated_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS print_requests (
            id                      TEXT PRIMARY KEY,
            student_national_id_hash TEXT REFERENCES students(national_id_hash),
            shop_id                 TEXT DEFAULT 'default',
            source                  TEXT DEFAULT 'lan',
            status                  TEXT DEFAULT 'received',
            verification_code       TEXT,
            notes                   TEXT,
            notification_method     TEXT DEFAULT 'none',
            contact                 TEXT,
            notification_sent       INTEGER DEFAULT 0,
            created_at              TEXT DEFAULT (datetime('now')),
            updated_at              TEXT DEFAULT (datetime('now')),
            delivered_at            TEXT,
            row_version             INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS request_files (
            id            TEXT PRIMARY KEY,
            request_id    TEXT REFERENCES print_requests(id) ON DELETE CASCADE,
            original_name TEXT,
            stored_path   TEXT,
            pages         INTEGER DEFAULT 0,
            copies        INTEGER DEFAULT 1,
            color         INTEGER DEFAULT 0,
            sides         TEXT DEFAULT 'single',
            file_size     INTEGER DEFAULT 0,
            mime_type     TEXT
        );

        CREATE TABLE IF NOT EXISTS library_files (
            id          TEXT PRIMARY KEY,
            path        TEXT UNIQUE,
            name        TEXT,
            pages       INTEGER DEFAULT 0,
            size        INTEGER DEFAULT 0,
            modified    TEXT,
            department  TEXT,
            stage       TEXT,
            subject     TEXT,
            professor   TEXT,
            hash        TEXT
        );

        CREATE TABLE IF NOT EXISTS outbox (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type  TEXT NOT NULL,
            payload     TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now')),
            processed   INTEGER DEFAULT 0,
            retries     INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS daily_stats (
            date                TEXT PRIMARY KEY,
            total_pages_printed INTEGER DEFAULT 0,
            total_requests      INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_requests_status
            ON print_requests(status);
        CREATE INDEX IF NOT EXISTS idx_requests_created
            ON print_requests(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_files_request
            ON request_files(request_id);
        CREATE INDEX IF NOT EXISTS idx_outbox_unprocessed
            ON outbox(processed) WHERE processed = 0;

        CREATE TABLE IF NOT EXISTS settings (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS telegram_chats (
            chat_id    TEXT PRIMARY KEY,
            username   TEXT,
            linked_at  TEXT DEFAULT (datetime('now'))
        );
    ''')

    # ── Migrations (safe ADD COLUMN for existing DBs) ─────────────────────────
    existing = {row[1] for row in cur.execute("PRAGMA table_info(print_requests)")}
    if 'rating' not in existing:
        cur.execute("ALTER TABLE print_requests ADD COLUMN rating INTEGER DEFAULT 0")
    if 'total_pages' not in existing:
        cur.execute("ALTER TABLE print_requests ADD COLUMN total_pages INTEGER DEFAULT 0")

    lib_cols = {row[1] for row in cur.execute("PRAGMA table_info(library_files)")}
    if 'indexed_at' not in lib_cols:
        cur.execute("ALTER TABLE library_files ADD COLUMN indexed_at TEXT DEFAULT (datetime('now'))")

    # ── Default settings ──────────────────────────────────────────────────────
    cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('setup_complete','0')")
    cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('operator_name','سعد')")
    cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('library_name','مكتبة جامعة الأنبار')")
    cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('library_path','')")

    conn.commit()
    conn.close()


def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, str) and len(v) > 0 and v[0] in ('{', '['):
            try:
                d[k] = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                pass
    return d
