"""Create and update playlists from an explicit track list.

This is the piece the Spotify connector cannot do: the track list is decided
here and sent verbatim, instead of being described in prose and handed to
Spotify's own generator.
"""

from kit.auth import call

# Spotify accepts at most 100 items per add/replace call. Items are bare track
# ids or full URIs: spotipy prefixes the former and passes episode URIs through.
CHUNK = 100


def create(client, name: str, track_ids: list[str], description: str = "", public: bool = False) -> dict:
    """Create a private playlist and fill it with the given tracks, in order."""
    if not track_ids:
        raise ValueError("Refusing to create an empty playlist")

    # spotipy still posts to /users/{id}/playlists, which Spotify retired in the
    # February 2026 migration and now answers with 403. The replacement is
    # POST /me/playlists, so this one call goes out raw.
    playlist = call(
        client._post,
        "me/playlists",
        payload={"name": name, "public": public, "description": description},
    )

    # Through call(): a quota 403 here would otherwise strand an empty playlist.
    for start in range(0, len(track_ids), CHUNK):
        call(client.playlist_add_items, playlist["id"], track_ids[start : start + CHUNK])

    return {"id": playlist["id"], "url": playlist["external_urls"]["spotify"], "added": len(track_ids)}


def replace_tracks(client, playlist_id: str, track_ids: list[str]) -> int:
    """Swap a playlist's contents for a new ordered list."""
    # The first call replaces; the rest append, which is how Spotify expects
    # a full rewrite of a playlist longer than 100 tracks.
    call(client.playlist_replace_items, playlist_id, track_ids[:CHUNK])
    for start in range(CHUNK, len(track_ids), CHUNK):
        call(client.playlist_add_items, playlist_id, track_ids[start : start + CHUNK])
    return len(track_ids)
