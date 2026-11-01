"""Local SQLite mirror of the Spotify library.

Holding the library on disk is what makes ad-hoc curation possible: rules like
"no artist twice" or "nothing played in the last 60 days" become plain SQL
instead of bespoke code.
"""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "library.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS artists (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    genres      TEXT,           -- comma separated, as returned by Spotify
    popularity  INTEGER,
    followers   INTEGER
);

CREATE TABLE IF NOT EXISTS tracks (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    artist_ids      TEXT NOT NULL,  -- comma separated
    artist_names    TEXT NOT NULL,
    album_id        TEXT,
    album_name      TEXT,
    release_date    TEXT,
    duration_ms     INTEGER,
    popularity      INTEGER,
    explicit        INTEGER,
    isrc            TEXT,           -- join key against Deezer
    bpm             REAL,           -- from Deezer; 0 means "known missing"
    gain            REAL,
    bpm_checked_at  TEXT            -- avoids re-querying Deezer every sync
);

CREATE INDEX IF NOT EXISTS idx_tracks_isrc ON tracks (isrc);

CREATE TABLE IF NOT EXISTS saved_tracks (
    track_id  TEXT PRIMARY KEY REFERENCES tracks (id),
    added_at  TEXT
);

CREATE TABLE IF NOT EXISTS playlists (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT,
    owner_id      TEXT,
    owner_name    TEXT,
    is_mine       INTEGER,
    public        INTEGER,
    collaborative INTEGER,
    total_tracks  INTEGER,
    snapshot_id   TEXT,
    synced_at     TEXT
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id  TEXT NOT NULL REFERENCES playlists (id),
    track_id     TEXT NOT NULL REFERENCES tracks (id),
    position     INTEGER NOT NULL,
    added_at     TEXT,
    PRIMARY KEY (playlist_id, position)
);

CREATE INDEX IF NOT EXISTS idx_pltracks_track ON playlist_tracks (track_id);

-- Snapshots of /me/top, one row per item per capture.
CREATE TABLE IF NOT EXISTS top_items (
    kind        TEXT NOT NULL,   -- 'artist' | 'track'
    time_range  TEXT NOT NULL,   -- short_term | medium_term | long_term
    rank        INTEGER NOT NULL,
    item_id     TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (kind, time_range, rank, captured_at)
);

-- Accumulated listening history. Spotify only ever returns the last 50 plays,
-- so this table is the only way a real history exists over time.
CREATE TABLE IF NOT EXISTS plays (
    played_at  TEXT PRIMARY KEY,
    track_id   TEXT NOT NULL,
    context    TEXT
);

CREATE INDEX IF NOT EXISTS idx_plays_track ON plays (track_id);
"""


def connect() -> sqlite3.Connection:
    """Open the library database, creating it and its schema on first use."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
