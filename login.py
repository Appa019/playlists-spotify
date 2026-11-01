"""One-time Spotify login. Opens a browser and caches the refresh token."""

from kit.auth import get_client

if __name__ == "__main__":
    client = get_client()
    me = client.current_user()
    print(f"Autenticado como {me['display_name']} ({me['id']}) — {me.get('product')}")
