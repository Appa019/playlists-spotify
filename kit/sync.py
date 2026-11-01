"""Pull the Spotify library into the local database."""

from datetime import datetime, timezone

from spotipy.exceptions import SpotifyException

from kit.auth import call, paginate

TOP_RANGES = ("short_term", "medium_term", "long_term")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_tracks(conn, tracks: list[dict]) -> None:
    """Store track rows, preserving any BPM already fetched for them."""
    for track in tracks:
        if not track or not track.get("id") or track.get("is_local"):
            continue
        album = track.get("album") or {}
        artists = track.get("artists") or []
        conn.execute(
            """
            INSERT INTO tracks (id, name, artist_ids, artist_names, album_id,
                                album_name, release_date, duration_ms,
                                popularity, explicit, isrc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = excluded.name,
                popularity = excluded.popularity
            """,
            (
                track["id"],
                track["name"],
                ",".join(a["id"] for a in artists if a.get("id")),
                ", ".join(a["name"] for a in artists),
                album.get("id"),
                album.get("name"),
                album.get("release_date"),
                track.get("duration_ms"),
                track.get("popularity"),
                int(bool(track.get("explicit"))),
                (track.get("external_ids") or {}).get("isrc"),
            ),
        )


def sync_saved_tracks(client, conn) -> int:
    """Mirror the user's liked songs."""
    page = call(client.current_user_saved_tracks, limit=50)
    items = paginate(client, page)
    upsert_tracks(conn, [item["track"] for item in items])
    conn.execute("DELETE FROM saved_tracks")
    conn.executemany(
        "INSERT OR REPLACE INTO saved_tracks (track_id, added_at) VALUES (?, ?)",
        [
            (item["track"]["id"], item["added_at"])
            for item in items
            if item.get("track") and item["track"].get("id")
        ],
    )
    conn.commit()
    return len(items)


def sync_playlists(client, conn, me_id: str) -> tuple[int, int, list[str]]:
    """Mirror every playlist the user owns or follows, including its tracks.

    Returns the playlist count, the track count, and the names of playlists
    whose contents Spotify refused to serve.
    """
    page = call(client.current_user_playlists, limit=50)
    playlists = [p for p in paginate(client, page) if p]

    track_total = 0
    unreadable: list[str] = []
    for playlist in playlists:
        owner = playlist.get("owner") or {}
        conn.execute(
            """
            INSERT OR REPLACE INTO playlists
                (id, name, description, owner_id, owner_name, is_mine, public,
                 collaborative, total_tracks, snapshot_id, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                playlist["id"],
                playlist["name"],
                playlist.get("description"),
                owner.get("id"),
                owner.get("display_name"),
                int(owner.get("id") == me_id),
                int(bool(playlist.get("public"))),
                int(bool(playlist.get("collaborative"))),
                (playlist.get("tracks") or {}).get("total"),
                playlist.get("snapshot_id"),
                _now(),
            ),
        )

        try:
            items = paginate(client, call(client.playlist_items, playlist["id"], limit=100))
        except SpotifyException as exc:
            # Spotify-owned and algorithmic playlists (Discover Weekly, On Repeat,
            # editorial mixes) return 403 for apps registered after Nov 2024. They
            # still show up in /me/playlists, so record them and move on.
            if exc.http_status in (403, 404):
                unreadable.append(playlist["name"])
                conn.commit()
                continue
            raise

        tracks = [item.get("track") for item in items]
        upsert_tracks(conn, tracks)

        conn.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist["id"],))
        rows = [
            (playlist["id"], item["track"]["id"], position, item.get("added_at"))
            for position, item in enumerate(items)
            if item.get("track") and item["track"].get("id") and not item["track"].get("is_local")
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO playlist_tracks
               (playlist_id, track_id, position, added_at) VALUES (?, ?, ?, ?)""",
            rows,
        )
        track_total += len(rows)
        conn.commit()

    return len(playlists), track_total, unreadable


def sync_artists(client, conn) -> int:
    """Fetch full artist records for everyone appearing in the library.

    Artist genres are the closest thing left to a taste signal now that
    audio-features is gone, so they are worth the extra calls.
    """
    ids = set()
    for row in conn.execute("SELECT artist_ids FROM tracks WHERE artist_ids != ''"):
        ids.update(row["artist_ids"].split(","))
    known = {row["id"] for row in conn.execute("SELECT id FROM artists")}
    missing = sorted(ids - known)

    # Development-mode apps get 403 on every batch endpoint (/artists?ids=,
    # /tracks?ids=, /albums?ids=), so these have to go one request per artist.
    fetched = 0
    for artist_id in missing:
        try:
            artist = call(client.artist, artist_id)
        except SpotifyException as exc:
            if exc.http_status in (403, 404):
                continue
            raise
        conn.execute(
            """INSERT OR REPLACE INTO artists (id, name, genres, popularity, followers)
               VALUES (?, ?, ?, ?, ?)""",
            (
                artist["id"],
                artist["name"],
                ",".join(artist.get("genres") or []),
                artist.get("popularity"),
                (artist.get("followers") or {}).get("total"),
            ),
        )
        fetched += 1
        if fetched % 100 == 0:
            conn.commit()
            print(f"  artistas: {fetched}/{len(missing)}")
    conn.commit()
    return fetched


def sync_top_items(client, conn) -> int:
    """Snapshot /me/top for artists and tracks across all three time ranges."""
    captured_at = _now()
    count = 0
    for time_range in TOP_RANGES:
        tracks = call(client.current_user_top_tracks, limit=50, time_range=time_range)["items"]
        upsert_tracks(conn, tracks)
        artists = call(client.current_user_top_artists, limit=50, time_range=time_range)["items"]
        for kind, items in (("track", tracks), ("artist", artists)):
            conn.executemany(
                """INSERT OR REPLACE INTO top_items
                   (kind, time_range, rank, item_id, captured_at) VALUES (?, ?, ?, ?, ?)""",
                [
                    (kind, time_range, rank, item["id"], captured_at)
                    for rank, item in enumerate(items, start=1)
                ],
            )
            count += len(items)
    conn.commit()
    return count


def sync_recent_plays(client, conn) -> int:
    """Append the last 50 plays. Existing rows are kept — this table only grows."""
    items = call(client.current_user_recently_played, limit=50)["items"]
    upsert_tracks(conn, [item["track"] for item in items])
    before = conn.execute("SELECT COUNT(*) AS n FROM plays").fetchone()["n"]
    conn.executemany(
        "INSERT OR IGNORE INTO plays (played_at, track_id, context) VALUES (?, ?, ?)",
        [
            (item["played_at"], item["track"]["id"], (item.get("context") or {}).get("uri"))
            for item in items
            if item.get("track") and item["track"].get("id")
        ],
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) AS n FROM plays").fetchone()["n"]
    return after - before
