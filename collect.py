"""Append recent plays to the local history. Meant to run from cron.

Spotify only ever returns the last 50 plays, so running this on a schedule is
the only way a real listening history accumulates.
"""

from kit.auth import get_client
from kit.sync import sync_recent_plays
from kit.db import connect

if __name__ == "__main__":
    conn = connect()
    added = sync_recent_plays(get_client(), conn)
    if added:
        print(f"{added} novos plays")
