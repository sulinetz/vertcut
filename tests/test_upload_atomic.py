"""Атомарная запись загрузок: рабочий файл не теряется при ошибке."""
from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from starlette.datastructures import UploadFile

from vertcut import downloader, main


def _upload(data: bytes, filename: str) -> UploadFile:
    return UploadFile(io.BytesIO(data), size=len(data), filename=filename)


class _Resp:
    def __init__(self, headers, chunks):
        self.headers = headers
        self.chunks = list(chunks)

    def read(self, size=-1):
        return self.chunks.pop(0) if self.chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class DownloadFileAtomicTest(unittest.TestCase):
    def test_progress_without_content_length_and_no_part_left(self):
        seen = []
        resp = _Resp({}, [b"x" * 4096, b"y" * 4096])
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("urllib.request.urlopen", return_value=resp):
            dest = Path(tmp)
            meta = downloader.download_file(
                "https://example.com/v.mp4", dest,
                progress=lambda p, st: seen.append((p, st)))
            self.assertEqual(meta["path"], dest / "source.mp4")
            self.assertTrue((dest / "source.mp4").exists())
            self.assertFalse((dest / "source.mp4.part").exists())
        self.assertTrue(seen, "прогресс должен идти и без Content-Length")
        self.assertIn("МБ", seen[0][1])

    def test_cancel_leaves_no_partial_file(self):
        resp = _Resp({"Content-Length": "8192"}, [b"x" * 4096, b"y" * 4096])

        def cancelled(_p, _stage):
            raise downloader.Cancelled()

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("urllib.request.urlopen", return_value=resp):
            dest = Path(tmp)
            with self.assertRaises(downloader.Cancelled):
                downloader.download_file("https://example.com/v.mp4", dest,
                                         progress=cancelled)
            self.assertFalse((dest / "source.mp4").exists())
            self.assertFalse((dest / "source.mp4.part").exists())


class StoreUploadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patcher = mock.patch.object(main, "PROJECTS_DIR", self.dir)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def _store(self, data: bytes, name: str):
        return asyncio.run(main._store_upload("p1", _upload(data, name)))

    def test_failed_probe_keeps_previous_source(self):
        workdir = self.dir / "p1"
        workdir.mkdir()
        old = workdir / "source.mp4"
        old.write_bytes(b"OLD" * 1024)
        broken = {"called": False}

        def bad_probe(_path):
            broken["called"] = True
            raise RuntimeError("не медиа")

        with mock.patch("vertcut.utils.probe", bad_probe), \
             mock.patch.object(main.db, "merge_meta", lambda *a, **k: None):
            with self.assertRaises(main.HTTPException) as ctx:
                self._store(b"x" * 4096, "video.mkv")
        self.assertTrue(broken["called"], "проверка должна идти по временному файлу")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(old.read_bytes(), b"OLD" * 1024, "рабочий исходник затёрт")
        self.assertEqual(sorted(p.name for p in workdir.iterdir()), ["source.mp4"])

    def test_success_replaces_and_drops_other_extensions(self):
        workdir = self.dir / "p1"
        workdir.mkdir()
        (workdir / "source.mp4").write_bytes(b"OLD" * 1024)
        with mock.patch("vertcut.utils.probe",
                        lambda _p: {"duration": 10.0, "audio_streams": []}), \
             mock.patch.object(main.db, "merge_meta", lambda *a, **k: None):
            target = self._store(b"x" * 4096, "video.mkv")
        self.assertEqual(target, workdir / "source.mkv")
        self.assertTrue(target.exists())
        self.assertFalse((workdir / "source.mp4").exists())
        self.assertFalse(list(workdir.glob("*.part")))


class UploadDubAtomicTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patcher = mock.patch.object(main, "PROJECTS_DIR", self.dir)
        self.patcher.start()
        self.project = {"id": "p1", "options": {}, "meta": {}}
        self.db = mock.patch.multiple(
            main.db,
            get_project=mock.Mock(return_value=dict(self.project)),
            merge_meta=mock.Mock(),
            update_project=mock.Mock(),
        )
        self.db.start()

    def tearDown(self):
        self.db.stop()
        self.patcher.stop()
        self.tmp.cleanup()

    def test_failed_probe_keeps_previous_dub(self):
        workdir = self.dir / "p1"
        workdir.mkdir()
        old = workdir / "dub.mka"
        old.write_bytes(b"OLD" * 1024)
        with mock.patch("vertcut.utils.probe_audio",
                        side_effect=RuntimeError("нет звука")):
            with self.assertRaises(main.HTTPException) as ctx:
                asyncio.run(main.upload_dub("p1", _upload(b"x" * 4096, "voice.m4a")))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(old.read_bytes(), b"OLD" * 1024)
        self.assertEqual(sorted(p.name for p in workdir.iterdir()), ["dub.mka"])

    def test_success_replaces_old_dub(self):
        workdir = self.dir / "p1"
        workdir.mkdir()
        (workdir / "dub.mka").write_bytes(b"OLD" * 1024)
        (workdir / "dub_subs_0.srt").write_text("1\n", encoding="utf-8")
        info = {"has_audio": True, "has_video": False, "duration": 5.0,
                "audio_streams": [], "sample_rate": 48000}
        with mock.patch("vertcut.utils.probe_audio", lambda _p: dict(info)):
            result = asyncio.run(main.upload_dub("p1", _upload(b"x" * 4096, "voice.m4a")))
        self.assertTrue(result["ok"])
        self.assertTrue((workdir / "dub.m4a").exists())
        self.assertFalse((workdir / "dub.mka").exists())
        self.assertFalse((workdir / "dub_subs_0.srt").exists())
        self.assertFalse(list(workdir.glob("*.part")))


if __name__ == "__main__":
    unittest.main()
