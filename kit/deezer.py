"""BPM enrichment via Deezer's public API.

Spotify removed audio-features for apps registered after Nov 2024, so tempo has
to come from elsewhere. Deezer exposes bpm and gain with no authentication and
shares the ISRC identifier with Spotify, which makes the join exact rather than
a fuzzy title match. Coverage is partial (~75% on Brazilian catalogue); a bpm
of 0 means Deezer knows the track but has no tempo for it.
"""

import time
from datetime import datetime, timezone

import httpx

API = "https://api.deezer.com"
# Deezer throttles around 50 requests per 5 seconds. Staying under it costs
# nothing here and avoids the quota errors that come back as empty payloads.
REQUEST_INTERVAL = 0.12


def fetch_by_isrc(isrc: str, client: httpx.Client) -> dict | None:
    """Look a track up by ISRC. Returns None when Deezer has no such track."""
    try:
        response = client.get(f"{API}/track/isrc:{isrc}", timeout=15)
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if "error" in payload or not payload.get("id"):
        return None
    return {"bpm": payload.get("bpm"), "gain": payload.get("gain")}


def enrich(conn, limit: int | None = None) -> dict:
    """Fill bpm/gain for tracks that have an ISRC and were never checked.

    Rows already checked are skipped, so repeated runs are cheap and only pick
    up whatever the last sync added.
    """
    rows = conn.execute(
        """
        SELECT id, isrc FROM tracks
        WHERE isrc IS NOT NULL AND isrc != '' AND bpm_checked_at IS NULL
        """
        + (f" LIMIT {int(limit)}" if limit else "")
    ).fetchall()

    stats = {"checked": 0, "with_bpm": 0, "not_found": 0}
    now = datetime.now(timezone.utc).isoformat()

    with httpx.Client() as client:
        for row in rows:
            result = fetch_by_isrc(row["isrc"], client)
            stats["checked"] += 1
            if result is None:
                stats["not_found"] += 1
                # Mark it checked anyway so the next run does not retry it.
                conn.execute(
                    "UPDATE tracks SET bpm_checked_at = ? WHERE id = ?", (now, row["id"])
                )
            else:
                if result["bpm"]:
                    stats["with_bpm"] += 1
                conn.execute(
                    "UPDATE tracks SET bpm = ?, gain = ?, bpm_checked_at = ? WHERE id = ?",
                    (result["bpm"], result["gain"], now, row["id"]),
                )
            if stats["checked"] % 100 == 0:
                conn.commit()
                print(f"  deezer: {stats['checked']}/{len(rows)}")
            time.sleep(REQUEST_INTERVAL)

    conn.commit()
    return stats
