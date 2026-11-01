"""Full library sync: Spotify into SQLite, then BPM enrichment from Deezer."""

import sys

from kit import deezer, sync
from kit.auth import get_client
from kit.db import DB_PATH, connect

if __name__ == "__main__":
    client = get_client()
    conn = connect()
    me_id = client.current_user()["id"]

    print("curtidas...")
    print(f"  {sync.sync_saved_tracks(client, conn)} faixas")

    print("playlists...")
    count, tracks, unreadable = sync.sync_playlists(client, conn, me_id)
    print(f"  {count} playlists, {tracks} faixas")
    if unreadable:
        print(f"  {len(unreadable)} sem acesso (algoritmicas/editoriais da Spotify):")
        for name in unreadable:
            print(f"    - {name}")

    print("top artistas/faixas...")
    print(f"  {sync.sync_top_items(client, conn)} registros")

    print("plays recentes...")
    print(f"  {sync.sync_recent_plays(client, conn)} novos")

    print("artistas...")
    print(f"  {sync.sync_artists(client, conn)} novos")

    if "--no-bpm" not in sys.argv:
        print("bpm via deezer...")
        stats = deezer.enrich(conn)
        print(f"  {stats['checked']} checadas, {stats['with_bpm']} com bpm")

    print(f"\npronto: {DB_PATH}")
