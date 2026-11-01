"""Create and update playlists from an explicit track list.

This is the piece the Spotify connector cannot do: the track list is decided
here and sent verbatim, instead of being described in prose and handed to
Spotify's own generator.
"""

CHUNK = 100  # Spotify accepts at most 100 URIs per add/replace call.


def _uris(track_ids: list[str]) -> list[str]:
    return [t if t.startswith("spotify:track:") else f"spotify:track:{t}" for t in track_ids]


def create(client, name: str, track_ids: list[str], description: str = "", public: bool = False) -> dict:
    """Create a private playlist and fill it with the given tracks, in order."""
    if not track_ids:
        raise ValueError("Refusing to create an empty playlist")

    # spotipy still posts to /users/{id}/playlists, which Spotify retired in the
    # February 2026 migration and now answers with 403. The replacement is
    # POST /me/playlists, so this one call goes out raw.
    playlist = client._post(
        "me/playlists",
        payload={"name": name, "public": public, "description": description},
    )

    uris = _uris(track_ids)
    for start in range(0, len(uris), CHUNK):
        client.playlist_add_items(playlist["id"], uris[start : start + CHUNK])

    return {"id": playlist["id"], "url": playlist["external_urls"]["spotify"], "added": len(uris)}


def replace_tracks(client, playlist_id: str, track_ids: list[str]) -> int:
    """Swap a playlist's contents for a new ordered list."""
    uris = _uris(track_ids)
    # The first call replaces; the rest append, which is how Spotify expects
    # a full rewrite of a playlist longer than 100 tracks.
    client.playlist_replace_items(playlist_id, uris[:CHUNK])
    for start in range(CHUNK, len(uris), CHUNK):
        client.playlist_add_items(playlist_id, uris[start : start + CHUNK])
    return len(uris)
