"""Предпросмотр кадра в мастере и выбор вшитой субтитровой дорожки."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vertcut import main, pipeline, reframe, utils
from vertcut.config import ffmpeg


class PreviewFrameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.src = cls.dir / "src.mp4"
        subprocess.run([ffmpeg(), "-y", "-v", "error",
                        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=2",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                        str(cls.src)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _project(self, duration=2.0):
        return {"id": "p1", "source": str(self.src), "duration": duration}

    def test_frame_is_extracted_and_cached(self):
        with mock.patch.object(main, "PROJECTS_DIR", self.dir), \
             mock.patch.object(main.db, "get_project", lambda _p: self._project()):
            first = main.project_frame("p1", t=1.0, width=320)
            second = main.project_frame("p1", t=1.0, width=320)
        path = Path(first.path)
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 1000)
        self.assertEqual(Path(second.path), path)

    def test_frame_info_returns_clamped_crop(self):
        with mock.patch.object(main.db, "get_project", lambda _p: self._project()):
            info = main.project_frame_info("p1", t=0.5, aspect="9:16")
        self.assertAlmostEqual(info["time"], 0.5, places=2)
        box = info["box"]
        self.assertIsNotNone(box)
        self.assertGreater(box["crop_w"], 0)
        self.assertGreaterEqual(box["x"], 0)
        self.assertLessEqual(box["x"] + box["crop_w"], box["source_w"])
        self.assertGreaterEqual(box["y"], 0)
        self.assertLessEqual(box["y"] + box["crop_h"], box["source_h"])

    def test_random_time_when_t_is_negative(self):
        with mock.patch.object(main.db, "get_project", lambda _p: self._project(20.0)), \
             mock.patch("vertcut.reframe.frame_box", lambda *a, **k: None):
            info = main.project_frame_info("p1", t=-1.0)
        self.assertGreaterEqual(info["time"], 0.0)
        self.assertLessEqual(info["time"], 20.0)

    def test_missing_source_is_404(self):
        with mock.patch.object(main.db, "get_project", lambda _p: {"id": "p1"}):
            with self.assertRaises(main.HTTPException) as ctx:
                main.project_frame("p1")
        self.assertEqual(ctx.exception.status_code, 404)


class SubtitleTrackTest(unittest.TestCase):
    def test_selected_track_is_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            source = workdir / "src.mkv"
            source.write_bytes(b"x")
            calls = {}

            def extract(_src, dst, index=0):
                calls["index"] = index
                Path(dst).write_text("1\n00:00:00,000 --> 00:00:01,000\nпривет\n",
                                     encoding="utf-8")
                return Path(dst)

            with mock.patch.object(utils, "subtitle_streams",
                                   lambda _p: [{"index": 0}, {"index": 2}]), \
                 mock.patch.object(utils, "extract_subtitles", extract):
                result = pipeline._existing_subtitles(source, workdir, track=2)
                self.assertTrue((workdir / "source_subs_2.srt").exists())
        self.assertIsNotNone(result)
        self.assertEqual(calls["index"], 2)
        self.assertEqual(result["segments"][0]["text"], "привет")

    def test_missing_selected_track_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            source = workdir / "src.mkv"
            source.write_bytes(b"x")
            with mock.patch.object(utils, "subtitle_streams",
                                   lambda _p: [{"index": 0}]), \
                 mock.patch.object(utils, "extract_subtitles",
                                   side_effect=AssertionError("не должно вызываться")):
                self.assertIsNone(pipeline._existing_subtitles(source, workdir, track=3))


class FrameBoxTest(unittest.TestCase):
    def test_crop_fits_source_without_faces(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v.mp4"
            subprocess.run([ffmpeg(), "-y", "-v", "error",
                            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=1",
                            "-c:v", "libx264", "-preset", "ultrafast",
                            "-pix_fmt", "yuv420p", str(path)], check=True)
            box = reframe.frame_box(path, 0.2, "9:16")
        self.assertIsNotNone(box)
        self.assertLessEqual(box["x"] + box["crop_w"], box["source_w"])
        self.assertLessEqual(box["y"] + box["crop_h"], box["source_h"])
        self.assertEqual(box["faces"], 0)


if __name__ == "__main__":
    unittest.main()