"""База: прерванные задачи, закрытие соединений и запись meta."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vertcut import db, pipeline


class TempDbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patcher = mock.patch.object(db, "DB_PATH", Path(self.tmp.name) / "t.db")
        self.patcher.start()
        db.init_db()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_reset_stale_jobs_marks_rendering_clips(self):
        project = db.create_project("local:source", {})
        db.update_project(project["id"], status="running")
        clip = db.add_clip(project["id"], 0, 0.0, 10.0, 0.5, "t", "", "", [], {},
                           status="rendering")
        db.reset_stale_jobs()
        self.assertEqual(db.get_project(project["id"])["status"], "error")
        broken = db.get_clip(clip["id"])
        self.assertEqual(broken["status"], "error")
        self.assertIn("прервано перезапуском", broken["error"] or "")

    def test_ready_clips_are_not_touched(self):
        project = db.create_project("local:source", {})
        clip = db.add_clip(project["id"], 0, 0.0, 10.0, 0.5, "t", "", "", [], {},
                           status="ready")
        db.reset_stale_jobs()
        self.assertEqual(db.get_clip(clip["id"])["status"], "ready")

    def test_connection_is_closed(self):
        closed = []
        real_connect = db.connect

        class Counting:
            def __init__(self, conn):
                self._conn = conn

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self._conn.__exit__(*args)

            def close(self):
                closed.append(True)
                self._conn.close()

            def __getattr__(self, name):
                return getattr(self._conn, name)

        with mock.patch.object(db, "connect", lambda: Counting(real_connect())):
            self.assertIsNone(db.get_project("nope"))
        self.assertTrue(closed, "соединение sqlite должно закрываться")


class DownloadMetaTest(unittest.TestCase):
    def test_meta_is_merged_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "p1"
            workdir.mkdir()
            (workdir / "source.mp4").write_bytes(b"x" * 4096)
            fake_db = mock.Mock()
            fake_db.get_project.return_value = {"id": "p1", "meta": {}}
            progress = mock.Mock()
            info = {"duration": 10.0, "width": 640, "height": 360,
                    "audio_streams": [{"index": 0, "language": "rus"}],
                    "sample_rate": 48000}
            with mock.patch.object(pipeline, "db", fake_db), \
                 mock.patch.object(pipeline.utils, "probe", lambda _p: dict(info)), \
                 mock.patch.object(pipeline, "PROJECTS_DIR", Path(tmp)):
                pipeline._download_phase(
                    "p1", {"url": "local:source", "title": "t"}, {}, workdir, progress)
            for call in fake_db.update_project.call_args_list:
                self.assertNotIn("meta", call.kwargs, "meta нельзя перезаписывать целиком")
            merged = [call.args[1] for call in fake_db.merge_meta.call_args_list]
            self.assertTrue(any("width" in item and "audio_tracks" in item
                                for item in merged), merged)


if __name__ == "__main__":
    unittest.main()
