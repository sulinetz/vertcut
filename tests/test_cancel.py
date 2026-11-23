"""Отмена: распознавание, загрузка, рендер и ретрай не должны её глотать."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from vertcut import downloader, jobs, main, pipeline, transcribe
from vertcut.errors import Cancelled


class FakeProc:
    def __init__(self, cmd, fail=False, killed=None, **_kwargs):
        self.cmd = cmd
        self.returncode = 1 if fail else 0
        self.stdout = iter(["out_time_us=1000000\n", "out_time_us=2000000\n"])
        self.stderr = iter([])
        self.killed = killed if killed is not None else {"hit": False}
        if not fail:
            target = Path(cmd[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x" * 20000)

    def wait(self):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed["hit"] = True
        self.returncode = -1


def _probe(_path):
    return {"width": 1920, "height": 1080, "duration": 60.0, "fps": 30.0,
            "has_audio": False, "sample_rate": 48000, "audio_streams": []}


class TranscribeCancelTest(unittest.TestCase):
    def test_cancelled_chunk_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            wav = workdir / "audio16k.wav"
            wav.write_bytes(b"x" * 16)
            with mock.patch.object(transcribe.utils, "probe",
                                   lambda _p: {"duration": 10.0, "has_audio": True,
                                               "width": 0, "height": 0}), \
                 mock.patch.object(transcribe.utils, "extract_asr_audio",
                                   lambda *a, **k: wav), \
                 mock.patch.object(transcribe, "_get_model", lambda **k: object()), \
                 mock.patch.object(transcribe, "_run_with_timeout",
                                   side_effect=Cancelled()):
                with self.assertRaises(Cancelled):
                    transcribe.transcribe(wav, workdir)


class _Resp:
    headers = {"Content-Length": str(1024 * 1024)}

    def __init__(self):
        self.served = False

    def read(self, size=-1):
        if self.served:
            return b""
        self.served = True
        return b"x" * size

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class DownloadFileCancelTest(unittest.TestCase):
    def test_cancel_from_progress_is_not_wrapped(self):
        def cancelled(_p, _stage):
            raise Cancelled()

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("urllib.request.urlopen", return_value=_Resp()):
            with self.assertRaises(Cancelled):
                downloader.download_file("https://example.com/v.mp4", Path(tmp),
                                         progress=cancelled)


class RenderCancelTest(unittest.TestCase):
    def test_render_kills_ffmpeg_when_cancelled(self):
        from vertcut import render

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            src = workdir / "src.mp4"
            src.write_bytes(b"x" * 100)
            out = workdir / "out.mp4"
            state = {"killed": {"hit": False}}
            calls = {"n": 0}

            def fake(cmd, **kw):
                return FakeProc(cmd, killed=state["killed"], **kw)

            def cancelled():
                calls["n"] += 1
                return calls["n"] > 1  # первый прогресс проходит, дальше отмена

            with mock.patch.object(render, "probe", _probe), \
                 mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
                 mock.patch.object(render, "hw_encoder", lambda: None), \
                 mock.patch.object(render, "subprocess") as sub:
                sub.Popen.side_effect = fake
                sub.PIPE = -1
                with self.assertRaises(Cancelled):
                    render.render_clip(src, 0.0, 10.0, out, mode="crop",
                                       is_cancelled=cancelled)
            self.assertTrue(state["killed"]["hit"], "ffmpeg должен быть убит")
            self.assertFalse(out.exists())


class JobsCancelTest(unittest.TestCase):
    class _SyncPool:
        def submit(self, fn):
            fn()

    def test_guarded_clears_cancel_flag_before_new_target(self):
        pipeline.request_cancel("p-cancel")
        ran = []
        with mock.patch.object(jobs, "_project_pool", self._SyncPool()), \
             mock.patch.object(jobs.db, "update_project", lambda *a, **k: None):
            jobs._guarded("p-cancel", lambda: ran.append("p-cancel"))
        self.assertEqual(ran, ["p-cancel"])
        self.assertNotIn("p-cancel", pipeline.CANCELLED)


class RetryCancelTest(unittest.TestCase):
    def test_retry_does_not_clear_cancel_immediately(self):
        project = {"id": "p1", "url": "https://example.com/v", "status": "cancelled",
                   "options": {}, "source": "x"}
        with mock.patch.object(main.db, "get_project", lambda _p: dict(project)), \
             mock.patch.object(main.db, "clear_clips", lambda _p: None), \
             mock.patch.object(main.db, "update_project", lambda *a, **k: None), \
             mock.patch.object(main.jobs, "is_running", lambda _p: True), \
             mock.patch.object(main.jobs, "submit_project", lambda _p: None), \
             mock.patch.object(main.pipeline, "request_cancel") as request, \
             mock.patch.object(main.pipeline, "clear_cancel") as clear:
            main.project_retry("p1")
        request.assert_called_once_with("p1")
        clear.assert_not_called()


if __name__ == "__main__":
    unittest.main()
