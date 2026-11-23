"""Сценарии process_project: готовые субтитры и отказ распознавания."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from vertcut import pipeline, transcribe


class FakeDB:
    """Минимальная замена sqlite-слоя: проект, клипы и записанные обновления."""

    def __init__(self, project):
        self.project = dict(project)
        self.project.setdefault("meta", {})
        self.clips = []
        self.updates = []

    def get_project(self, pid):
        return dict(self.project) if pid == self.project["id"] else None

    def update_project(self, pid, **fields):
        self.project.update(fields)
        self.updates.append(fields)

    def merge_meta(self, pid, updates, drop=()):
        self.project.setdefault("meta", {}).update(updates)

    def list_clips(self, pid):
        return [dict(c) for c in self.clips]

    def add_clip(self, pid, idx, start, end, score, title, hook, caption,
                 words, settings, status="rendering"):
        clip = {"id": f"c{idx}", "project_id": pid, "idx": idx, "start": start,
                "end": end, "words": words, "settings": settings, "status": status}
        self.clips.append(clip)
        return dict(clip)

    def update_clip(self, cid, **fields):
        for clip in self.clips:
            if clip["id"] == cid:
                clip.update(fields)

    def clear_clips(self, pid):
        self.clips.clear()


class _NoThread:
    def join(self, timeout=None):
        return None


class ProcessProjectCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "source.mp4"
        self.src.write_bytes(b"x" * 2048)
        self.workdir = self.dir / "p1"
        self.workdir.mkdir()
        self.db = FakeDB({
            "id": "p1", "url": "local:source", "title": "t", "source": str(self.src),
            "duration": 20.0, "meta": {}, "options": {
                "count": 1, "subtitles": True, "select": "smart",
                "min_dur": 8, "max_dur": 60, "target_dur": 20,
            },
        })
        pipeline.clear_cancel("p1")

    def tearDown(self):
        pipeline.clear_cancel("p1")
        self.tmp.cleanup()

    def _run(self, transcript_error=True, fetch=None, find=None, probe=None):
        candidate = {
            "start": 0.0, "end": 10.0, "score": 0.5, "title": "Момент",
            "hook": "", "caption": "",
            "words": [{"word": "слово", "start": 0.2, "end": 1.0}], "parts": {},
        }

        def boom(*_a, **_k):
            raise transcribe.TranscriptionError("речи нет")

        def fake_render(_source, _workdir, clip, _settings, _progress=None):
            self.db.update_clip(clip["id"], status="ready", error=None)

        patches = [
            mock.patch.object(pipeline, "db", self.db),
            mock.patch.object(pipeline, "PROJECTS_DIR", self.dir),
            mock.patch.object(pipeline.utils, "probe",
                              probe or (lambda _p: {"duration": 20.0, "width": 640,
                                                    "height": 360})),
            mock.patch.object(pipeline, "_existing_subtitles", lambda *a, **k: None),
            mock.patch.object(pipeline, "_heartbeat",
                              lambda *a, **k: (threading.Event(), _NoThread())),
            mock.patch.object(pipeline.transcribe, "model_cached", lambda: True),
            mock.patch.object(pipeline.transcribe, "transcribe",
                              boom if transcript_error else (lambda *a, **k: {
                                  "language": "ru", "duration": 20.0,
                                  "segments": [{"start": 0.2, "end": 1.0, "text": "слово",
                                                "words": [{"word": "слово", "start": 0.2,
                                                           "end": 1.0}]}],
                                  "engine": "whisper-test"})),
            mock.patch.object(pipeline, "_render_one", fake_render),
            mock.patch.object(pipeline, "_render_workers", lambda: 1),
            mock.patch.object(pipeline.analyze, "find_segments",
                              lambda *a, **k: find or [candidate]),
        ]
        fetcher = fetch if fetch is not None else mock.Mock(return_value=None)
        patches.append(mock.patch.object(pipeline.downloader, "fetch_subtitles", fetcher))
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        pipeline.process_project("p1")
        return fetcher

    def test_language_comes_from_downloaded_subtitles(self):
        # язык берём из файла субтитров, а не хардкодим "ru"
        self.db.project["url"] = "https://example.com/v"
        sub_path = self.dir / "subs.en.vtt"
        sub_path.write_text("WEBVTT\n", encoding="utf-8")
        fetcher = mock.Mock(return_value=(sub_path, "en"))
        with mock.patch.object(pipeline.utils, "parse_vtt", lambda _p: [
            {"start": 0.0, "end": 5.0, "text": "hello",
             "words": [{"word": "hello", "start": 0.0, "end": 5.0}]},
        ]):
            self._run(transcript_error=True, fetch=fetcher)
        self.assertEqual(self.db.project["status"], "done")
        self.assertEqual(self.db.project.get("language"), "en")

    def test_local_project_does_not_fetch_subtitles(self):
        # у локального файла нет страницы-источника: качать субтитры неоткуда
        fetcher = self._run(transcript_error=True)
        fetcher.assert_not_called()

    def test_transcription_error_falls_back_to_even_split(self):
        # речи нет и субтитров нет: режем на равные части, а не падаем на None
        self._run(transcript_error=True)
        self.assertEqual(self.db.project["status"], "done")
        self.assertIsNone(self.db.project.get("language"))
        self.assertEqual(len(self.db.clips), 1)
        self.assertEqual(self.db.clips[0]["status"], "ready")

    def test_probe_error_is_reported_not_raised(self):
        def broken(_path):
            raise pipeline.utils.MediaError("файл повреждён")

        self._run(transcript_error=True, probe=broken)
        self.assertEqual(self.db.project["status"], "error")
        self.assertIn("повреждён", self.db.project.get("error") or "")


if __name__ == "__main__":
    unittest.main()
