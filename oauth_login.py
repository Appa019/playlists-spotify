"""One-time OAuth login with an explicit local callback server.

Spotipy's built-in browser flow behaves differently depending on the terminal,
so the redirect is handled here instead: the script prints the authorize URL,
serves 127.0.0.1:8888 until Spotify redirects back with a code, then exchanges
it and writes the token cache spotipy reads on later runs.
"""

import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

from kit.auth import DATA_DIR, ROOT, SCOPES, TOKEN_CACHE

PAGE = b"<html><body style='font-family:sans-serif;padding:3rem'>" \
       b"<h2>Pronto.</h2><p>Pode fechar esta aba e voltar ao terminal.</p></body></html>"


class CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        CallbackHandler.code = (params.get("code") or [None])[0]
        CallbackHandler.error = (params.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args):
        pass  # keep the console clean


def main() -> None:
    load_dotenv(ROOT / ".env")
    DATA_DIR.mkdir(exist_ok=True)

    auth = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope=SCOPES,
        cache_path=str(TOKEN_CACHE),
        open_browser=False,
    )

    print("ABRA ESTA URL:", auth.get_authorize_url(), flush=True)

    server = HTTPServer(("127.0.0.1", 8888), CallbackHandler)
    server.timeout = 300
    while CallbackHandler.code is None and CallbackHandler.error is None:
        server.handle_request()
    server.server_close()

    if CallbackHandler.error:
        raise SystemExit(f"Spotify recusou: {CallbackHandler.error}")

    auth.get_access_token(code=CallbackHandler.code, as_dict=False)
    print("TOKEN_SALVO", flush=True)


if __name__ == "__main__":
    main()
