"""Перерендер с расширением границ берёт слова из сохранённого транскрипта."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vertcut import pipeline

TRANSCRIPT = {
    "language": "ru", "duration": 30.0,
    "segments": [
        {"start": 4.0, "end": 7.0, "text": "раньше", "words": [
            {"word": "раньше", "start": 4.0, "end": 5.0},
            {"word": "начало", "start": 6.0, "end": 7.0}]},
        {"start": 11.0, "end": 13.0, "text": "внутри", "words": [
            {"word": "внутри", "start": 11.0, "end": 12.0}]},
    ],
}

CLIP = {
    "id": "c1", "project_id": "p1", "idx": 0, "start": 10.0, "end": 20.0,
    "title": "t", "hook": "", "caption": "", "status": "ready",
    "words": [{"word": "внутри", "start": 11.0, "end": 12.0}],
    "settings": {"aspect": "9:16"},
}


class TranscriptReuseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.workdir = self.dir / "p1"
        self.workdir.mkdir()
        (self.workdir / "transcript.json").write_text(
            json.dumps(TRANSCRIPT, ensure_ascii=False), encoding="utf-8")
        self.src = self.dir / "src.mp4"
        self.src.write_bytes(b"x" * 100)
        self.updated = {}

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, payload):
        clip = dict(CLIP)

        def update(_cid, **fields):
            self.updated.update(fields)

        with mock.patch.object(pipeline, "PROJECTS_DIR", self.dir), \
             mock.patch.object(pipeline.db, "get_clip", lambda _c: dict(clip)), \
             mock.patch.object(pipeline.db, "get_project",
                               lambda _p: {"id": "p1", "source": str(self.src),
                                           "options": {}, "duration": 30.0}), \
             mock.patch.object(pipeline.db, "update_clip", update), \
             mock.patch.object(pipeline, "_render_one", lambda *a, **k: None):
            pipeline.rerender_clip("c1", payload)
        return self.updated

    def test_extending_start_pulls_earlier_words(self):
        fields = self._run({"start": 3.0, "end": 20.0})
        words = fields.get("words") or []
        self.assertIn("раньше", [w["word"] for w in words])
        self.assertIn("начало", [w["word"] for w in words])
        self.assertIn("внутри", [w["word"] for w in words])

    def test_no_transcript_falls_back_to_clip_words(self):
        (self.workdir / "transcript.json").unlink()
        fields = self._run({"start": 9.0, "end": 20.0})
        words = fields.get("words") or []
        self.assertEqual([w["word"] for w in words], ["внутри"])

    def test_unchanged_bounds_keep_clip_words(self):
        fields = self._run({})
        words = fields.get("words") or []
        self.assertEqual([w["word"] for w in words], ["внутри"])


if __name__ == "__main__":
    unittest.main()