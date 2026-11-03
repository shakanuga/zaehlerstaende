"""SQLite-Schema und Grunddaten."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin','member')),
  can_record INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meters (
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  unit TEXT NOT NULL,
  decimals INTEGER NOT NULL DEFAULT 3,
  color TEXT NOT NULL DEFAULT 'wasser',
  private INTEGER NOT NULL DEFAULT 0,
  parent_id INTEGER REFERENCES meters(id),
  sort INTEGER NOT NULL DEFAULT 100,
  active INTEGER NOT NULL DEFAULT 1,
  number TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS readings (
  id INTEGER PRIMARY KEY,
  meter_id INTEGER NOT NULL REFERENCES meters(id),
  read_on TEXT NOT NULL,
  value REAL NOT NULL,
  new_meter INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '',
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT,
  deleted_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS readings_unique
  ON readings(meter_id, read_on) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS readings_meter ON readings(meter_id, read_on);
CREATE TABLE IF NOT EXISTS photos (
  id INTEGER PRIMARY KEY,
  reading_id INTEGER NOT NULL REFERENCES readings(id),
  path TEXT NOT NULL,
  original_name TEXT NOT NULL DEFAULT '',
  mime TEXT NOT NULL,
  size INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  taken_at TEXT,
  uploaded_at TEXT NOT NULL,
  superseded_at TEXT
);
CREATE INDEX IF NOT EXISTS photos_reading ON photos(reading_id);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  user_id INTEGER REFERENCES users(id),
  user_name TEXT NOT NULL,
  action TEXT NOT NULL,
  meter_id INTEGER,
  reading_id INTEGER,
  old_json TEXT,
  new_json TEXT,
  reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS audit_reading ON audit(reading_id);
"""

DEFAULT_METERS = [
    # key, name, unit, decimals, color, private, sort
    ("gas", "Gas", "m³", 3, "gas", 0, 10),
    ("strom", "Strom", "kWh", 1, "strom", 0, 20),
    ("wasser", "Wasser Hauptzähler", "m³", 3, "wasser", 0, 30),
    ("wasser_klein", "Kleiner Wasserzähler", "m³", 3, "wasser", 1, 40),
]


def connect(path):
    con = sqlite3.connect(path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def init(path):
    con = connect(path)
    con.executescript(SCHEMA)
    if not con.execute("SELECT 1 FROM meters LIMIT 1").fetchone():
        for row in DEFAULT_METERS:
            con.execute(
                "INSERT INTO meters(key,name,unit,decimals,color,private,sort) VALUES (?,?,?,?,?,?,?)", row
            )
        con.execute(
            "UPDATE meters SET parent_id=(SELECT id FROM meters WHERE key='wasser') WHERE key='wasser_klein'"
        )
    con.commit()
    con.close()
