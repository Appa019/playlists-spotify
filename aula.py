"""Narrated music lessons on Spotify: AI explanation, example tracks, repeat.

    python aula.py publish lessons/jazz.json   # narration -> mp3 -> podcast feed
    python aula.py build lessons/jazz.json     # episodes + tracks -> playlist

Spotify needs a while to ingest new episodes from the feed, so `build` runs
after `publish` once they show up; it says which ones are still missing.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from kit import playlist, podcast
from kit.auth import DATA_DIR, ROOT, call, get_client, paginate

# Lesson slug -> playlist id, so rebuilding a lesson updates its playlist
# instead of piling up copies.
PLAYLISTS = DATA_DIR / "aulas.json"


def env(*names: str) -> list[str]:
    load_dotenv(ROOT / ".env")
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        sys.exit(f"Faltando no .env: {', '.join(missing)}")
    return [os.environ[n] for n in names]


def resolve_track(client, track: dict) -> dict | None:
    """Spotify track for {"artist", "title"}, or just {"id"} when the lesson pins one."""
    if track.get("id"):
        return {"id": track["id"]}
    # Quotes inside a name (Take the "A" Train) would end the quoted filter early.
    title, artist = (track[k].replace('"', "") for k in ("title", "artist"))
    query = f'track:"{title}" artist:"{artist}"'
    items = call(client.search, q=query, type="track", limit=10)["tracks"]["items"]
    want = track["artist"].casefold()
    # Search ranks loosely, so only accept a hit whose artist really matches
    # ("Miles Davis" also matches "Miles Davis Quintet").
    for item in items:
        if any(want in a["name"].casefold() or a["name"].casefold() in want for a in item["artists"]):
            return item
    return None


def show_episodes(client, show_id: str) -> dict[str, str]:
    """Episode title -> URI for every episode Spotify has ingested so far."""
    episodes = paginate(client, call(client.show_episodes, show_id, limit=50))
    return {ep["name"]: ep["uri"] for ep in episodes if ep}


def build(lesson: dict) -> None:
    (show_id,) = env("SPOTIFY_SHOW_ID")
    client = get_client()
    episodes = show_episodes(client, show_id)

    sequence, missing = [], []
    for index, segment in enumerate(lesson["segments"], start=1):
        title = podcast.episode_title(lesson, index)
        if title in episodes:
            sequence.append(episodes[title])
        else:
            missing.append(f"episódio não está no Spotify (rodou publish? ingestão leva horas): {title}")
        for track in segment["tracks"]:
            found = resolve_track(client, track)
            if found:
                sequence.append(found["id"])
                # Album and year show which recording was picked; pin "id" in
                # the lesson when it is the wrong one.
                if "album" in found:
                    album = found["album"]
                    print(f"  {found['artists'][0]['name']} - {found['name']} [{album['name']}, {album['release_date'][:4]}] {found['id']}")
            else:
                missing.append(f"faixa não encontrada: {track['artist']} - {track['title']}")

    # A half-built lesson would play out of order, so refuse until all is there.
    if missing:
        sys.exit("\n".join(missing))

    known = json.loads(PLAYLISTS.read_text()) if PLAYLISTS.exists() else {}
    if lesson["slug"] in known:
        playlist.replace_tracks(client, known[lesson["slug"]], sequence)
        print(f"playlist atualizada: https://open.spotify.com/playlist/{known[lesson['slug']]}")
    else:
        result = playlist.create(client, lesson["title"], sequence, description=lesson.get("description", ""))
        known[lesson["slug"]] = result["id"]
        PLAYLISTS.write_text(json.dumps(known, indent=2) + "\n")
        print(f"playlist criada: {result['url']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["publish", "build"])
    parser.add_argument("lesson", type=Path)
    args = parser.parse_args()
    try:
        lesson = json.loads(args.lesson.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"não consegui ler a aula {args.lesson}: {exc}")

    if args.command == "publish":
        podcast_dir, base_url, email, api_key = env("PODCAST_DIR", "PODCAST_URL", "PODCAST_EMAIL", "OPENROUTER_API_KEY")
        base_url = base_url.rstrip("/")
        try:
            changed = podcast.publish(lesson, ROOT / Path(podcast_dir).expanduser(), base_url, email, api_key)
        except ValueError as exc:
            sys.exit(str(exc))
        print(f"feed: {base_url}/feed.xml (episódios novos ou regravados: {len(changed)})")
        for title in changed:
            print(f"  {title}")
    else:
        build(lesson)


if __name__ == "__main__":
    main()
