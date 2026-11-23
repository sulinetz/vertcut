"""Валидация правок клипа и отмены; потоковые загрузки."""
from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from starlette.datastructures import UploadFile

from vertcut import main

CLIP = {"id": "c1", "project_id": "p1", "start": 10.0, "end": 20.0,
        "words": [], "settings": {}, "idx": 0, "title": "t", "hook": "", "caption": ""}
PROJECT = {"id": "p1", "source": "src.mp4", "duration": 60.0, "status": "review"}


class RerenderValidationTest(unittest.TestCase):
    def _call(self, **payload):
        clip = dict(CLIP)
        submitted = mock.Mock()
        with mock.patch.object(main.db, "get_clip", lambda _c: dict(clip)), \
             mock.patch.object(main.db, "get_project", lambda _p: dict(PROJECT)), \
             mock.patch.object(main.jobs, "submit_rerender", submitted):
            result = main.clip_rerender("c1", main.ClipEdit(**payload))
        return result, submitted

    def test_end_must_be_after_start(self):
        with self.assertRaises(main.HTTPException) as ctx:
            self._call(start=15.0, end=10.0)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_end_must_fit_source(self):
        with self.assertRaises(main.HTTPException) as ctx:
            self._call(start=10.0, end=90.0)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("пределы", ctx.exception.detail)

    def test_valid_edit_is_submitted(self):
        _result, submitted = self._call(start=10.0, end=30.0)
        submitted.assert_called_once()
        self.assertEqual(submitted.call_args.args[1]["end"], 30.0)


class CancelValidationTest(unittest.TestCase):
    def test_cancel_only_active(self):
        with mock.patch.object(main.db, "get_project",
                               lambda _p: {"id": "p1", "status": "review"}), \
             mock.patch.object(main.pipeline, "request_cancel") as request:
            with self.assertRaises(main.HTTPException) as ctx:
                main.project_cancel("p1")
        self.assertEqual(ctx.exception.status_code, 409)
        request.assert_not_called()

    def test_cancel_running_project(self):
        with mock.patch.object(main.db, "get_project",
                               lambda _p: {"id": "p1", "status": "running"}), \
             mock.patch.object(main.db, "update_project"), \
             mock.patch.object(main.pipeline, "request_cancel") as request:
            self.assertTrue(main.project_cancel("p1")["ok"])
        request.assert_called_once_with("p1")


class StreamUploadTest(unittest.TestCase):
    def test_limit_is_enforced_and_part_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "music.mp3"
            upload = UploadFile(io.BytesIO(b"x" * 40), size=40, filename="music.mp3")
            with self.assertRaises(main.HTTPException) as ctx:
                asyncio.run(main._stream_upload(upload, target, 20, "слишком большой"))
            self.assertEqual(ctx.exception.status_code, 413)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name(target.name + ".part").exists())

    def test_successful_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "music.mp3"
            upload = UploadFile(io.BytesIO(b"x" * 40), size=40, filename="music.mp3")
            asyncio.run(main._stream_upload(upload, target, 100, "слишком большой"))
            self.assertEqual(target.read_bytes(), b"x" * 40)
            self.assertFalse(target.with_name(target.name + ".part").exists())


class ThreadpoolTest(unittest.TestCase):
    def test_probe_goes_to_threadpool(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            seen = []

            async def runner(fn, *args, **kwargs):
                seen.append(getattr(fn, "__name__", ""))
                return fn(*args, **kwargs)

            def fake_probe(_path):
                return {"duration": 10.0, "audio_streams": []}

            with mock.patch.object(main, "PROJECTS_DIR", dest), \
                 mock.patch.object(main, "run_in_threadpool", side_effect=runner), \
                 mock.patch("vertcut.utils.probe", fake_probe), \
                 mock.patch.object(main.db, "merge_meta", lambda *a, **k: None):
                upload = UploadFile(io.BytesIO(b"x" * 2048), size=2048, filename="v.mp4")
                asyncio.run(main._store_upload("p1", upload))
        self.assertIn("fake_probe", seen)


if __name__ == "__main__":
    unittest.main()