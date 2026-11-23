"""Загрузчик: выбор формата, готовые субтитры, прямая загрузка файла."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vertcut import downloader

FORMATS = [
    {"format_id": "18", "ext": "mp4", "height": 360, "vcodec": "avc1.42001E",
     "acodec": "mp4a.40.2", "tbr": 600},
    {"format_id": "137", "ext": "mp4", "height": 1080, "vcodec": "avc1.640028",
     "acodec": "none", "tbr": 4500},
    {"format_id": "136", "ext": "mp4", "height": 720, "vcodec": "avc1.4d401f",
     "acodec": "none", "tbr": 2500},
    {"format_id": "140", "ext": "m4a", "height": None, "vcodec": "none",
     "acodec": "mp4a.40.2", "abr": 128},
]


class PickFormatTest(unittest.TestCase):
    def test_height_beats_muxed_audio(self):
        # 18 — 360p со звуком, но нужен 1080p и отдельная дорожка звука
        fmt, height = downloader._pick_format({"formats": FORMATS}, 1080)
        self.assertEqual(fmt, "137+140")
        self.assertEqual(height, 1080)

    def test_limit_picks_best_below_cap(self):
        fmt, height = downloader._pick_format({"formats": FORMATS}, 720)
        self.assertEqual(fmt, "136+140")
        self.assertEqual(height, 720)

    def test_avc1_wins_at_same_height(self):
        formats = list(FORMATS) + [
            {"format_id": "248", "ext": "webm", "height": 1080, "vcodec": "vp9",
             "acodec": "none", "tbr": 4000},
        ]
        fmt, _height = downloader._pick_format({"formats": formats}, 1080)
        self.assertEqual(fmt, "137+140")


class FmtErrTest(unittest.TestCase):
    def test_word_boundaries_do_not_misfire(self):
        text = downloader._fmt_err(Exception("Design in CSS is broken"))
        self.assertEqual(text, "Design in CSS is broken")
        text = downloader._fmt_err(Exception("package page not found"))
        self.assertNotIn("возраст", text)

    def test_auth_and_private_messages(self):
        self.assertIn("авторизацию", downloader._fmt_err(Exception("Sign in to confirm")))
        self.assertIn("приватное", downloader._fmt_err(Exception("Private video")))

    def test_no_old_brand_in_format_error(self):
        text = downloader._fmt_err(Exception("Requested format is not available"))
        self.assertNotIn("Вайралкат", text)
        self.assertIn("приложение", text)


class CleanPartialsTest(unittest.TestCase):
    def test_fragments_are_removed_but_valid_source_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            keep = dest / "source.mp4"
            keep.write_bytes(b"x" * 2048)
            for name in ("source.f137.mp4", "source.f251.webm", "source.f137.mp4.part",
                         "source.f251.webm.ytdl"):
                (dest / name).write_bytes(b"x")
            downloader._clean_partials(dest)
            self.assertTrue(keep.exists())
            self.assertFalse(list(dest.glob("source.f*")))


class FetchSubtitlesTest(unittest.TestCase):
    """Готовые субтитры: русские в приоритете, старые файлы не подхватываются."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _fetch(self, writer):
        with mock.patch("yt_dlp.YoutubeDL") as ydl:
            ydl.return_value.__enter__.return_value.download.side_effect = writer
            return downloader.fetch_subtitles("https://example.com/v", self.dir)

    def test_russian_is_preferred_over_english(self):
        def write(_urls):
            (self.dir / "subs.en.vtt").write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nhello\n",
                                                  encoding="utf-8")
            (self.dir / "subs.ru.vtt").write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nпривет\n",
                                                  encoding="utf-8")

        path, language = self._fetch(write)
        self.assertEqual(Path(path).name, "subs.ru.vtt")
        self.assertEqual(language, "ru")

    def test_english_is_used_when_russian_is_missing(self):
        def write(_urls):
            (self.dir / "subs.en.vtt").write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nhello\n",
                                                  encoding="utf-8")

        path, language = self._fetch(write)
        self.assertEqual(Path(path).name, "subs.en.vtt")
        self.assertEqual(language, "en")

    def test_stale_file_is_removed_before_download(self):
        stale = self.dir / "subs.ru.vtt"
        stale.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nстарое\n", encoding="utf-8")
        self.assertIsNone(self._fetch(lambda _urls: None))
        self.assertFalse(stale.exists(), "старые субтитры должны быть удалены до загрузки")

    def test_language_less_file_has_empty_language(self):
        def write(_urls):
            (self.dir / "subs.vtt").write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nhi\n",
                                               encoding="utf-8")

        path, language = self._fetch(write)
        self.assertEqual(Path(path).name, "subs.vtt")
        self.assertEqual(language, "")


if __name__ == "__main__":
    unittest.main()
