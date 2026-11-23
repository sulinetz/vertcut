"""Внешняя звуковая дорожка (дубляж): сдвиг, куски, ffmpeg и настройки."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vertcut import pipeline, render, timeline, utils

DUB_PROBE = {
    "duration": 100.0,
    "has_audio": True,
    "has_video": False,
    "sample_rate": 44100,
    "audio_streams": [
        {"index": 0, "language": "rus", "codec": "aac", "sample_rate": 44100,
         "channels": "stereo", "default": True},
    ],
}


class FakeProc:
    def __init__(self, cmd, fail=False, **_kwargs):
        self.cmd = cmd
        self.returncode = 1 if fail else 0
        self.stdout = iter(["out_time_us=1000000\n"])
        self.stderr = iter([])
        if not fail:
            target = Path(cmd[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x" * 20000)

    def wait(self):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -1


def _probe(_path):
    return {"width": 1920, "height": 1080, "duration": 60.0, "fps": 30.0,
            "has_audio": True, "height_ok": True, "sample_rate": 48000,
            "audio_streams": [{"index": 0, "language": "jpn", "sample_rate": 48000,
                               "default": True}]}


class DubPiecesTest(unittest.TestCase):
    def test_no_offset_keeps_segments(self):
        self.assertEqual(timeline.dub_pieces([(0.0, 10.0)], 0.0, 100.0),
                         [{"audio": True, "start": 0.0, "end": 10.0}])

    def test_positive_offset_pads_the_head(self):
        pieces = timeline.dub_pieces([(0.0, 10.0)], 2.0, 100.0)
        self.assertEqual(pieces[0], {"audio": False, "duration": 2.0})
        self.assertEqual(pieces[1], {"audio": True, "start": 0.0, "end": 8.0})

    def test_negative_offset_skips_the_head(self):
        self.assertEqual(timeline.dub_pieces([(0.0, 10.0)], -2.0, 100.0),
                         [{"audio": True, "start": 2.0, "end": 12.0}])

    def test_short_file_pads_the_tail(self):
        pieces = timeline.dub_pieces([(0.0, 10.0)], 0.0, 5.0)
        self.assertEqual(pieces[0], {"audio": True, "start": 0.0, "end": 5.0})
        self.assertEqual(pieces[1], {"audio": False, "duration": 5.0})

    def test_segment_outside_file_is_silent(self):
        self.assertEqual(timeline.dub_pieces([(10.0, 20.0)], 0.0, 5.0),
                         [{"audio": False, "duration": 10.0}])

    def test_total_length_matches_clip(self):
        pieces = timeline.dub_pieces([(0.0, 3.0), (7.0, 12.0)], 1.5, 10.0)
        total = sum(p["duration"] if not p["audio"] else p["end"] - p["start"]
                    for p in pieces)
        self.assertAlmostEqual(total, 8.0, places=2)


class ShiftWordsTest(unittest.TestCase):
    def test_shifts_and_clamps_to_video(self):
        words = [{"word": "a", "start": 0.5, "end": 1.0},
                 {"word": "b", "start": 8.5, "end": 9.0}]
        shifted = timeline.shift_words(words, 0.5, duration=10.0)
        self.assertEqual(len(shifted), 2)
        self.assertAlmostEqual(shifted[0]["start"], 1.0, places=3)
        self.assertAlmostEqual(shifted[1]["end"], 9.5, places=3)

    def test_end_is_clamped_at_video_border(self):
        words = [{"word": "b", "start": 9.0, "end": 9.9}]
        shifted = timeline.shift_words(words, 0.5, duration=10.0)
        self.assertEqual(len(shifted), 1)
        self.assertAlmostEqual(shifted[0]["end"], 10.0, places=3)

    def test_drops_words_outside_video(self):
        words = [{"word": "a", "start": 0.0, "end": 1.0}]
        self.assertEqual(timeline.shift_words(words, -5.0, duration=10.0), [])

    def test_transcript_moves_segments_and_words(self):
        segments = [{"start": 1.0, "end": 2.0, "text": "привет",
                     "words": [{"word": "привет", "start": 1.0, "end": 2.0}]}]
        shifted = timeline.shift_transcript(segments, 2.0, duration=10.0)
        self.assertEqual(len(shifted), 1)
        self.assertAlmostEqual(shifted[0]["start"], 3.0, places=3)
        self.assertAlmostEqual(shifted[0]["words"][0]["start"], 3.0, places=3)


class ProbeAudioTest(unittest.TestCase):
    SAMPLE = (
        "Input #0, matroska,webm, from 'dub.mka':\n"
        "  Duration: 00:24:01.50, start: 0.000000, bitrate: 192 kb/s\n"
        "  Stream #0:0(rus): Audio: aac (LC), 44100 Hz, stereo, fltp (default)\n"
    )

    def test_audio_only_file_is_readable(self):
        proc = subprocess.CompletedProcess([], 0, "", self.SAMPLE)
        with mock.patch.object(utils, "run", return_value=proc):
            info = utils.probe_audio(Path("dub.mka"))
        self.assertTrue(info["has_audio"])
        self.assertFalse(info["has_video"])
        self.assertEqual(info["sample_rate"], 44100)
        self.assertAlmostEqual(info["duration"], 1441.5, places=2)

    def test_bitmap_subtitles_still_count_for_mapping(self):
        text = (
            "  Stream #0:2(eng): Subtitle: hdmv_pgs_subtitle\n"
            "  Stream #0:3(rus): Subtitle: subrip (default)\n"
        )
        proc = subprocess.CompletedProcess([], 0, "", text)
        with mock.patch.object(utils, "run", return_value=proc):
            tracks = utils.subtitle_streams(Path("dub.mkv"))
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["index"], 1)  # -map 0:s:1, bitmap занимает 0:s:0
        self.assertEqual(tracks[0]["language"], "rus")


class ExternalAudioRenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "src.mp4"
        self.src.write_bytes(b"x" * 100)
        self.dub = self.dir / "dub.mka"
        self.dub.write_bytes(b"x" * 100)
        self.out = self.dir / "out.mp4"

    def tearDown(self):
        self.tmp.cleanup()

    def _render(self, dub_info=None, clip_start=0.0, **kwargs):
        made = []

        def fake(cmd, **kw):
            proc = FakeProc(cmd, **kw)
            made.append(proc.cmd)
            return proc

        info = dub_info if dub_info is not None else DUB_PROBE
        with mock.patch.object(render, "probe", _probe), \
             mock.patch.object(render, "probe_audio", lambda _p: dict(info)), \
             mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
             mock.patch.object(render, "hw_encoder", lambda: None), \
             mock.patch.object(render, "subprocess") as sub:
            sub.Popen.side_effect = fake
            sub.PIPE = -1
            render.render_clip(self.src, clip_start, clip_start + 10.0, self.out, **kwargs)
        return made[0]

    def test_dub_pieces_use_absolute_clip_time(self):
        # клип начинается на 100-й секунде: atrim должен брать те же секунды
        # из полной дорожки дубляжа, а не 0..3 от начала файла.
        info = dict(DUB_PROBE)
        info["duration"] = 200.0
        cmd = self._render(dub_info=info, clip_start=100.0,
                           external_audio=self.dub, segments=[(0.0, 3.0), (5.0, 6.0)])
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("[1:a]atrim=start=100.000:end=103.000", graph)
        self.assertIn("[1:a]atrim=start=105.000:end=106.000", graph)

    def test_absolute_time_respects_positive_offset(self):
        info = dict(DUB_PROBE)
        info["duration"] = 200.0
        cmd = self._render(dub_info=info, clip_start=100.0, external_audio=self.dub,
                           segments=[(0.0, 3.0), (5.0, 6.0)], audio_offset=2.0)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("[1:a]atrim=start=98.000:end=101.000", graph)
        self.assertIn("[1:a]atrim=start=103.000:end=104.000", graph)

    def test_absolute_time_respects_negative_offset(self):
        info = dict(DUB_PROBE)
        info["duration"] = 200.0
        cmd = self._render(dub_info=info, clip_start=100.0, external_audio=self.dub,
                           segments=[(0.0, 3.0), (5.0, 6.0)], audio_offset=-1.5)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("[1:a]atrim=start=101.500:end=104.500", graph)

    def test_short_dub_pads_absolute_segments(self):
        info = dict(DUB_PROBE)
        info["duration"] = 102.5
        cmd = self._render(dub_info=info, clip_start=100.0, external_audio=self.dub,
                           segments=[(0.0, 3.0), (5.0, 6.0)])
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("atrim=start=100.000:end=102.500", graph)
        self.assertIn("aevalsrc=0|0:s=44100:d=0.500", graph)
        self.assertIn("aevalsrc=0|0:s=44100:d=1.000", graph)

    def test_dub_replaces_source_audio(self):
        cmd = self._render(external_audio=self.dub)
        self.assertIn(str(self.dub), cmd)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("[1:a]atrim=start=0.000:end=10.000", graph)
        self.assertNotIn("[0:a]", graph)
        self.assertIn("[a0]", graph)

    def test_offset_moves_dub_timeline(self):
        cmd = self._render(external_audio=self.dub, audio_offset=2.0)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("aevalsrc=0|0:s=44100:d=2.000", graph)
        self.assertIn("[1:a]atrim=start=0.000:end=8.000", graph)
        self.assertIn("concat=n=2:v=0:a=1[seq_a]", graph)

    def test_short_dub_gets_silence_tail(self):
        info = dict(DUB_PROBE)
        info["duration"] = 5.0
        cmd = self._render(external_audio=self.dub, dub_info=info)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("atrim=start=0.000:end=5.000", graph)
        self.assertIn("aevalsrc=0|0:s=44100:d=5.000", graph)

    def test_missing_dub_falls_back_to_source(self):
        missing = self.dir / "nope.mka"
        cmd = self._render(external_audio=missing)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("[0:a]", graph)
        self.assertNotIn("aevalsrc", graph)

    def test_dub_track_index_is_used(self):
        info = dict(DUB_PROBE)
        info["audio_streams"] = [
            {"index": 0, "language": "jpn", "sample_rate": 48000, "default": False},
            {"index": 1, "language": "rus", "sample_rate": 44100, "default": True},
        ]
        cmd = self._render(external_audio=self.dub, external_audio_track=1, dub_info=info)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("[1:a:1]", graph)


class ExternalAudioOptionsTest(unittest.TestCase):
    def test_defaults_are_neutral(self):
        opts = pipeline.normalize_options({})
        self.assertFalse(opts["external_audio"])
        self.assertEqual(opts["external_audio_track"], -1)
        self.assertEqual(opts["audio_offset"], 0.0)

    def test_values_are_clamped(self):
        opts = pipeline.normalize_options({
            "external_audio": True, "external_audio_track": 999, "audio_offset": 9999,
        })
        self.assertTrue(opts["external_audio"])
        self.assertEqual(opts["external_audio_track"], 64)
        self.assertEqual(opts["audio_offset"], 300.0)

    def test_clip_settings_keep_external_audio(self):
        settings = pipeline._clip_settings(pipeline.normalize_options({
            "external_audio": True, "external_audio_track": 2, "audio_offset": -1.5,
        }))
        self.assertTrue(settings["external_audio"])
        self.assertEqual(settings["external_audio_track"], 2)
        self.assertEqual(settings["audio_offset"], -1.5)

    def test_dub_only_when_enabled_and_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            (workdir / "dub.mka").write_bytes(b"x" * 4096)
            self.assertIsNone(pipeline._external_audio_path(workdir, {}))
            self.assertEqual(pipeline._external_audio_path(workdir, {"external_audio": True}),
                             workdir / "dub.mka")


if __name__ == "__main__":
    unittest.main()
