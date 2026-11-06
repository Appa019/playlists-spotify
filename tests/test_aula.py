"""Offline checks for the lesson pipeline: feed shape, titles, publish, track matching.

    .venv/bin/python -m unittest discover tests
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree as ET

from aula import resolve_track
from kit import podcast

ROOT = Path(__file__).resolve().parent.parent


class FakeSearch:
    def __init__(self, items):
        self.items = items
        self.queries = []

    def search(self, q, type, limit):
        self.queries.append(q)
        return {"tracks": {"items": self.items}}


class LessonTest(unittest.TestCase):
    def test_feed_has_what_spotify_needs(self):
        eps = [{"guid": "jazz-01", "file": "jazz-01-abcd1234.mp3", "title": "T", "description": "D", "bytes": 123, "pub_date": "Thu, 05 Nov 2026 12:00:00 +0000"}]
        root = ET.fromstring(podcast.build_feed("https://x.github.io/p", "me@example.com", eps))
        it = f"{{{podcast.ITUNES}}}"
        self.assertEqual(root.find(f"channel/{it}owner/{it}email").text, "me@example.com")
        self.assertEqual(root.find(f"channel/{it}image").get("href"), "https://x.github.io/p/cover.jpg")
        enclosure = root.find("channel/item/enclosure")
        self.assertEqual(enclosure.get("url"), "https://x.github.io/p/episodes/jazz-01-abcd1234.mp3")
        self.assertEqual(enclosure.get("length"), "123")

    def test_sample_lesson_is_valid(self):
        lesson = json.loads((ROOT / "lessons/jazz.json").read_text())
        titles = [podcast.episode_title(lesson, i) for i in range(1, len(lesson["segments"]) + 1)]
        self.assertEqual(len(set(titles)), len(titles))
        self.assertEqual(titles[0], "Jazz 101 1: New Orleans, where it all began")
        for seg in lesson["segments"]:
            self.assertLessEqual(len(seg["narration"]), podcast.MAX_CHARS)
            self.assertTrue(seg["tracks"])

    def test_publish_tracks_lesson_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote, repo = Path(tmp) / "remote.git", Path(tmp) / "repo"
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
            subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)

            fake_tts = mock.patch.object(podcast, "synthesize", side_effect=lambda text, out, key: (out.parent.mkdir(exist_ok=True), out.write_bytes(text.encode())))
            lesson = {"slug": "s", "title": "L", "segments": [{"title": "A", "narration": "one"}]}
            publish = lambda: podcast.publish(lesson, repo, "https://h", "e@x", "k")

            with fake_tts as tts:
                self.assertEqual(publish(), ["L 1: A"])
                self.assertEqual(publish(), [])  # nothing changed: no TTS, nothing new
                self.assertEqual(tts.call_count, 1)

                # Edited narration and a new segment: the first is re-voiced, keeps its date.
                first = json.loads((repo / "episodes.json").read_text())[0]
                lesson["segments"] = [{"title": "A2", "narration": "uno"}, {"title": "B", "narration": "two"}]
                self.assertEqual(publish(), ["L 1: A2", "L 2: B"])
                eps = json.loads((repo / "episodes.json").read_text())
                self.assertEqual([e["title"] for e in eps], ["L 1: A2", "L 2: B"])
                self.assertEqual(eps[0]["pub_date"], first["pub_date"])
                self.assertEqual(eps[0]["bytes"], 3)
                self.assertFalse((repo / "episodes" / first["file"]).exists())

            # Everything reached the remote, so a failed push would have shown up here.
            log = subprocess.run(["git", "--git-dir", str(remote), "log", "--oneline"], capture_output=True, text=True, check=True)
            self.assertEqual(len(log.stdout.splitlines()), 2)

    def test_publish_refuses_non_repo_before_tts(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(podcast, "synthesize") as tts:
            with self.assertRaises(ValueError):
                podcast.publish({"slug": "s", "title": "L", "segments": []}, Path(tmp), "u", "e", "k")
            tts.assert_not_called()

    def test_track_match_requires_artist(self):
        hits = [
            {"id": "cover", "artists": [{"name": "Some Cover Band"}]},
            {"id": "real", "artists": [{"name": "Miles Davis Quintet"}]},
        ]
        client = FakeSearch(hits)
        self.assertEqual(resolve_track(client, {"artist": "Miles Davis", "title": 'So "What"'})["id"], "real")
        self.assertEqual(client.queries[0], 'track:"So What" artist:"Miles Davis"')
        self.assertIsNone(resolve_track(FakeSearch(hits[:1]), {"artist": "Miles Davis", "title": "So What"}))
        self.assertEqual(resolve_track(client, {"artist": "x", "title": "y", "id": "given"}), {"id": "given"})


if __name__ == "__main__":
    unittest.main()
