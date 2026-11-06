"""Narrated music lessons published as a podcast feed.

Spotify takes no uploaded audio through its API, so each narration becomes a
podcast episode instead: synthesized by ElevenLabs (through OpenRouter),
written as mp3 + RSS into a public GitHub Pages repo, and ingested by Spotify
from that feed. Playlists can then mix those episodes with regular tracks.
"""

import hashlib
import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

TTS_URL = "https://openrouter.ai/api/v1/audio/speech"
TTS_MODEL = "elevenlabs/eleven-v4"
TTS_VOICE = "george"
# OpenRouter documents no input cap; ElevenLabs v3 stops at 5,000 characters,
# so stay under that rather than find the v4 limit with a paid failure.
MAX_CHARS = 4800

PODCAST_TITLE = "Music Lessons"
PODCAST_DESCRIPTION = "Short narrated lessons on music styles, each followed by example tracks."
ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES)


def episode_title(lesson: dict, index: int) -> str:
    """Stable title, also how `build` finds the episode on Spotify.

    No "i/n" total in it: adding a segment must not rename episodes already out.
    """
    return f"{lesson['title']} {index}: {lesson['segments'][index - 1]['title']}"


def synthesize(text: str, out: Path, api_key: str) -> None:
    """Turn narration text into an mp3 at `out`."""
    if len(text) > MAX_CHARS:
        raise ValueError(f"Narração com {len(text)} caracteres; divida abaixo de {MAX_CHARS}")

    for attempt in range(3):
        resp = httpx.post(
            TTS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": TTS_MODEL, "input": text, "voice": TTS_VOICE, "response_format": "mp3"},
            timeout=300,
        )
        # 429 is rate limiting and 5xx upstream trouble, so those are worth
        # another try; anything else is a request problem a retry won't fix.
        if resp.status_code in (429, 500, 502, 503) and attempt < 2:
            time.sleep(5 * 2**attempt)
            continue
        break

    if resp.status_code != 200:
        raise RuntimeError(f"TTS falhou ({resp.status_code}): {resp.text[:300]}")
    if not resp.headers.get("content-type", "").startswith("audio/mpeg"):
        raise RuntimeError(f"TTS devolveu {resp.headers.get('content-type')}, esperado audio/mpeg")

    # Write then rename, so an interrupted run never leaves a truncated mp3
    # that the cache check would later mistake for a finished one.
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(".part")
    partial.write_bytes(resp.content)
    partial.rename(out)


def build_feed(base_url: str, email: str, episodes: list[dict]) -> bytes:
    """Render the RSS document Spotify reads. `email` is public: Spotify sends its ownership code there."""
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = PODCAST_TITLE
    ET.SubElement(channel, "link").text = base_url
    ET.SubElement(channel, "description").text = PODCAST_DESCRIPTION
    ET.SubElement(channel, "language").text = "en"
    ET.SubElement(channel, f"{{{ITUNES}}}author").text = PODCAST_TITLE
    ET.SubElement(channel, f"{{{ITUNES}}}image", {"href": f"{base_url}/cover.jpg"})
    ET.SubElement(channel, f"{{{ITUNES}}}category", {"text": "Music"})
    ET.SubElement(channel, f"{{{ITUNES}}}explicit").text = "false"
    owner = ET.SubElement(channel, f"{{{ITUNES}}}owner")
    ET.SubElement(owner, f"{{{ITUNES}}}name").text = PODCAST_TITLE
    ET.SubElement(owner, f"{{{ITUNES}}}email").text = email

    for ep in episodes:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = ep["title"]
        ET.SubElement(item, "description").text = ep["description"]
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = ep["guid"]
        ET.SubElement(item, "pubDate").text = ep["pub_date"]
        ET.SubElement(
            item,
            "enclosure",
            {"url": f"{base_url}/episodes/{ep['file']}", "length": str(ep["bytes"]), "type": "audio/mpeg"},
        )

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def publish(lesson: dict, podcast_dir: Path, base_url: str, email: str, api_key: str) -> list[str]:
    """Synthesize changed narrations, rewrite the feed and push it. Returns titles of new or re-voiced episodes."""
    # Checked before any paid TTS call: a wrong path would otherwise burn
    # credits and only fail at the git step.
    if not (podcast_dir / ".git").exists():
        raise ValueError(f"{podcast_dir} não é um clone git do repo do podcast")

    manifest_path = podcast_dir / "episodes.json"
    manifest = {ep["guid"]: ep for ep in json.loads(manifest_path.read_text())} if manifest_path.exists() else {}
    now = datetime.now(timezone.utc)
    changed = []

    for index, segment in enumerate(lesson["segments"], start=1):
        guid = f"{lesson['slug']}-{index:02d}"
        # The text hash names the file: Spotify only re-fetches audio whose
        # enclosure URL changed, and an edited narration gets a fresh synthesis.
        digest = hashlib.sha256(segment["narration"].encode()).hexdigest()[:8]
        file = f"{guid}-{digest}.mp3"
        mp3 = podcast_dir / "episodes" / file
        if not mp3.exists():
            print(f"  tts {guid} ({len(segment['narration'])} caracteres)")
            synthesize(segment["narration"], mp3, api_key)

        old = manifest.get(guid, {})
        if old.get("file") != file:
            changed.append(episode_title(lesson, index))
            if old.get("file"):
                (podcast_dir / "episodes" / old["file"]).unlink(missing_ok=True)
        # Title and text follow the lesson on every run; only the first pub date
        # sticks, one second apart to keep the lesson's order in the show.
        manifest[guid] = {
            "guid": guid,
            "title": episode_title(lesson, index),
            "description": segment.get("summary") or segment["title"],
            "file": file,
            "bytes": mp3.stat().st_size,
            "pub_date": old.get("pub_date") or format_datetime(now + timedelta(seconds=index)),
        }

    episodes = list(manifest.values())
    manifest_path.write_text(json.dumps(episodes, indent=2, ensure_ascii=False) + "\n")
    (podcast_dir / "feed.xml").write_bytes(build_feed(base_url, email, episodes))

    git = ["git", "-C", str(podcast_dir)]
    subprocess.run([*git, "add", "-A"], check=True)
    if subprocess.run([*git, "diff", "--cached", "--quiet"]).returncode:
        subprocess.run([*git, "commit", "-q", "-m", f"feat: publish {lesson['slug']} episodes"], check=True)
    # Always push: a push that failed last run left a local commit and no diff.
    subprocess.run([*git, "push", "-q"], check=True)
    return changed
