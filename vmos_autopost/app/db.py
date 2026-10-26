import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices(
  pad_code TEXT PRIMARY KEY,
  label TEXT,
  current_username TEXT
);
CREATE TABLE IF NOT EXISTS accounts(
  username TEXT PRIMARY KEY,
  kode TEXT NOT NULL UNIQUE,
  pad_code TEXT NOT NULL REFERENCES devices(pad_code),
  status_akun TEXT
);
CREATE TABLE IF NOT EXISTS videos(
  id TEXT PRIMARY KEY,
  master_path TEXT NOT NULL,
  checksum TEXT
);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL REFERENCES accounts(username),
  pad_code TEXT NOT NULL REFERENCES devices(pad_code),
  video_id TEXT NOT NULL REFERENCES videos(id),
  batch TEXT NOT NULL DEFAULT '',
  caption TEXT,
  product_link TEXT,
  prompt TEXT,
  status TEXT NOT NULL,
  prev_status TEXT,
  attempt INTEGER NOT NULL DEFAULT 1,
  device_file_path TEXT,
  cleanup_status TEXT NOT NULL DEFAULT 'NONE',
  cleanup_attempts INTEGER NOT NULL DEFAULT 0,
  video_post_id TEXT,
  evidence TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  needs_operator_since TEXT,
  verified_at TEXT,
  finished_at TEXT,
  UNIQUE(username, video_id, batch)
);
CREATE TABLE IF NOT EXISTS task_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id),
  from_status TEXT,
  to_status TEXT NOT NULL,
  actor TEXT NOT NULL,
  reason TEXT,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS device_locks(
  pad_code TEXT PRIMARY KEY,
  task_id INTEGER NOT NULL,
  locked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cleanup_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  pad_code TEXT NOT NULL,
  path TEXT NOT NULL,
  result TEXT NOT NULL,
  detail TEXT,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings(
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


def connect(path):
    conn = sqlite3.connect(path, isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(path):
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
        if "product_link" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN product_link TEXT")
        if "prompt" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN prompt TEXT")
        cols_accts = {r["name"] for r in conn.execute("PRAGMA table_info(accounts)")}
        if "label" not in cols_accts:
            conn.execute("ALTER TABLE accounts ADD COLUMN label TEXT")
        if "status_akun" not in cols_accts:
            conn.execute("ALTER TABLE accounts ADD COLUMN status_akun TEXT")
    finally:
        conn.close()


@contextmanager
def read(path):
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def tx(path):
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def get_setting(path, key: str, default: str = None) -> str:
    with read(path) as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(path, key: str, value: str):
    with tx(path) as conn:
        conn.execute(
            "INSERT INTO app_settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value)
        )


