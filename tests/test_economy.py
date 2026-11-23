"""Экономный режим: фрагмент по ссылке и сдвиг слов относительно секции."""
from __future__ import annotations

import http.server
import re
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from vertcut import downloader, pipeline, utils
from vertcut.config import ffmpeg

MEDIA = {}


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        data = MEDIA["bytes"]
        rng = self.headers.get("Range")
        if rng:
            match = re.match(r"bytes=(\d+)-(\d*)", rng)
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else len(data) - 1
            chunk = data[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class DirectSectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        source = cls.dir / "source.mp4"
        subprocess.run(
            [ffmpeg(), "-y", "-v", "error",
             "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=10",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
             "-c:v", "libx264", "-preset", "ultrafast", "-g", "30",
             "-c:a", "aac", "-shortest", str(source)], check=True)
        MEDIA["bytes"] = source.read_bytes()
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/v.mp4"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def test_section_is_downloaded_by_ffmpeg(self):
        dest = self.dir / "section"
        part = downloader.download_section(self.url, dest, 3.0, 6.0,
                                           progress=lambda p, s: None)
        info = utils.probe(part)
        self.assertTrue(part.exists())
        self.assertTrue(info["has_audio"])
        self.assertGreater(part.stat().st_size, 10000)
        self.assertAlmostEqual(info["duration"], 3.0, delta=0.6)


class SegmentShiftTest(unittest.TestCase):
    def _run(self, actual: float):
        clip = {"id": "c1", "idx": 0, "project_id": "p1", "start": 10.0, "end": 14.0,
                "status": "pending", "words": [
                    {"word": "первое", "start": 10.2, "end": 11.0},
                    {"word": "второе", "start": 13.0, "end": 13.5}]}
        project = {"id": "p1", "url": "http://example/v.mp4", "duration": 30.0}
        captured = {}
        fake_db = mock.Mock()
        fake_db.list_clips.return_value = [dict(clip)]
        fake_db.get_project.return_value = dict(project)

        def render(_source, _workdir, virtual, _settings, _progress=None, **_kw):
            captured.update(virtual)

        with tempfile.TemporaryDirectory() as tmp:
            part = Path(tmp) / "section.mp4"
            part.write_bytes(b"x" * 2048)
            with mock.patch.object(pipeline, "db", fake_db), \
                 mock.patch.object(pipeline, "PROJECTS_DIR", Path(tmp)), \
                 mock.patch.object(pipeline.downloader, "download_section",
                                   lambda *a, **k: part), \
                 mock.patch.object(pipeline.utils, "media_duration", lambda _p: actual), \
                 mock.patch.object(pipeline, "_render_one", render):
                pipeline._process_segments(
                    "p1", project, pipeline.normalize_options({"segments": True}),
                    Path(tmp) / "p1", lambda *_a: None)
        return captured, fake_db

    def test_words_are_shifted_to_section_start(self):
        virtual, fake_db = self._run(8.0)
        words = virtual["words"]
        self.assertAlmostEqual(words[0]["start"], 0.7, places=3)
        self.assertAlmostEqual(words[1]["start"], 3.5, places=3)
        self.assertAlmostEqual(virtual["start"], 0.5, places=3)
        self.assertAlmostEqual(virtual["end"], 4.5, places=3)
        self.assertTrue(fake_db.update_clip.called)

    def test_short_section_truncates_clip(self):
        virtual, _db = self._run(3.0)
        self.assertAlmostEqual(virtual["end"], 3.0, places=3)


if __name__ == "__main__":
    unittest.main()