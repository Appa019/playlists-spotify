"""Authenticated Spotify client.

Uses the Authorization Code flow. The first run opens a browser and spins up a
local callback server on the redirect URI; the refresh token is cached in
data/.token-cache so later runs are non-interactive.
"""

import os
import time
from pathlib import Path

import spotipy
from spotipy.exceptions import SpotifyException
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

# Everything the toolkit needs: read the library, read listening history,
# read every playlist (including private/collaborative), and write playlists.
SCOPES = " ".join(
    [
        "user-library-read",
        "user-top-read",
        "user-read-recently-played",
        "playlist-read-private",
        "playlist-read-collaborative",
        "playlist-modify-private",
        "playlist-modify-public",
    ]
)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TOKEN_CACHE = DATA_DIR / ".token-cache"


def get_client() -> spotipy.Spotify:
    """Return an authenticated Spotify client, prompting for login if needed."""
    load_dotenv(ROOT / ".env")
    DATA_DIR.mkdir(exist_ok=True)

    missing = [
        name
        for name in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REDIRECT_URI")
        if not os.getenv(name)
    ]
    if missing:
        raise RuntimeError(f"Missing in .env: {', '.join(missing)}")

    auth = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope=SCOPES,
        cache_path=str(TOKEN_CACHE),
        open_browser=True,
    )
    # requests_timeout guards against the API hanging; retries cover 5xx blips.
    return spotipy.Spotify(auth_manager=auth, requests_timeout=30, retries=3)


# Development-mode apps have a low request quota and, unhelpfully, answer 403
# rather than 429 once it is exceeded — which reads exactly like a permission
# error. Spacing requests out keeps the whole sync under the ceiling.
MIN_INTERVAL = 0.25
_last_call = 0.0


def throttle() -> None:
    """Space consecutive API calls out to stay inside the dev-mode quota."""
    global _last_call
    elapsed = time.monotonic() - _last_call
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_call = time.monotonic()


def call(fn, *args, attempts: int = 4, **kwargs):
    """Run a Spotify call politely, backing off when the quota pushes back.

    A 403 is retried rather than raised on the first try, because throttling and
    genuine denial are indistinguishable by status code here. Only a 403 that
    survives every retry is treated as a real refusal.
    """
    for attempt in range(attempts):
        throttle()
        try:
            return fn(*args, **kwargs)
        except SpotifyException as exc:
            if exc.http_status in (403, 429) and attempt < attempts - 1:
                time.sleep(2**attempt)
                continue
            raise


def paginate(client: spotipy.Spotify, page: dict) -> list[dict]:
    """Collect every item across a paginated Spotify response."""
    items = list(page["items"])
    while page.get("next"):
        page = call(client.next, page)
        items.extend(page["items"])
    return items
