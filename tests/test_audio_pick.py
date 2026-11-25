"""Автовыбор русской аудиодорожки: чистая функция и селекторы yt-dlp."""
from __future__ import annotations

import pytest

from vertcut import downloader, pipeline, utils


def streams(*items):
    return [{"index": i, "stream": i + 1, "language": lang, "codec": codec,
             "sample_rate": rate, "channels": channels, "default": default}
            for i, (lang, codec, rate, channels, default) in enumerate(items)]


MULTI = streams(
    ("jpn", "flac", 48000, "stereo", False),
    ("rus", "aac", 44100, "stereo", True),
    ("eng", "aac", 48000, "stereo", False),
)

NO_RU = streams(
    ("eng", "aac", 48000, "stereo", False),
    ("deu", "aac", 44100, "stereo", True),
)


def test_russian_track_wins_among_languages():
    assert utils.pick_audio_track(MULTI, prefer=("ru", "rus")) == 1


def test_best_russian_track_wins_over_worse_russian():
    tracks = streams(("rus", "aac", 44100, "mono", False),
                     ("rus", "aac", 48000, "stereo", True))
    assert utils.pick_audio_track(tracks, prefer=("ru",)) == 1


def test_without_russian_falls_back_to_best_available():
    assert utils.pick_audio_track(NO_RU, prefer=("ru",)) == 1  # default + 44100
    assert utils.pick_audio_track(NO_RU, prefer=("ru",), allow_default=False) is None


def test_explicit_choice_overrides_language():
    opts = {"audio_track": 2, "audio_lang": "ru"}
    assert pipeline._resolve_audio_track(opts, MULTI) == 2


def test_language_choice_used_when_track_not_set():
    opts = {"audio_track": -1, "audio_lang": "ru"}
    assert pipeline._resolve_audio_track(opts, MULTI) == 1


def test_auto_language_preserves_old_behaviour():
    opts = {"audio_track": -1, "audio_lang": "auto"}
    assert pipeline._resolve_audio_track(opts, MULTI) is None
    assert pipeline._resolve_audio_track({}, MULTI) is None


def test_empty_stream_list_and_single_track():
    assert utils.pick_audio_track([], prefer=("ru",)) is None
    one = streams(("", "aac", 48000, "stereo", True))
    assert utils.pick_audio_track(one, prefer=("ru",)) == 0


def test_describe_audio_pick_is_human_readable():
    assert "русская дорожка 2 из 3" in utils.describe_audio_pick(MULTI, 1)
    assert "дорожка по умолчанию" in utils.describe_audio_pick(MULTI, None)
    assert utils.describe_audio_pick([], None) == "дорожка по умолчанию"


def test_apply_audio_pick_records_index_and_reason(monkeypatch):
    saved = {}
    monkeypatch.setattr(pipeline.db, "merge_meta",
                        lambda pid, meta: saved.update(meta))
    opts = {"audio_track": -1, "audio_lang": "ru"}
    assert pipeline._apply_audio_pick("p1", opts, MULTI) == 1
    assert opts["audio_track"] == 1
    pick = saved["audio_pick"]
    assert pick["index"] == 1
    assert pick["language"] == "rus"
    assert pick["reason"] == "language"
    assert pick["requested"] == "ru"


def test_apply_audio_pick_marks_missing_language(monkeypatch):
    saved = {}
    monkeypatch.setattr(pipeline.db, "merge_meta",
                        lambda pid, meta: saved.update(meta))
    opts = {"audio_track": -1, "audio_lang": "ru"}
    assert pipeline._apply_audio_pick("p1", opts, NO_RU) == 1
    assert saved["audio_pick"]["reason"] == "fallback"


def test_apply_audio_pick_keeps_manual_choice(monkeypatch):
    saved = {}
    monkeypatch.setattr(pipeline.db, "merge_meta",
                        lambda pid, meta: saved.update(meta))
    opts = {"audio_track": 2, "audio_lang": "ru"}
    assert pipeline._apply_audio_pick("p1", opts, MULTI) == 2
    assert saved["audio_pick"]["reason"] == "manual"


def test_auto_language_leaves_track_unset(monkeypatch):
    saved = {}
    monkeypatch.setattr(pipeline.db, "merge_meta",
                        lambda pid, meta: saved.update(meta))
    opts = {"audio_track": -1, "audio_lang": "auto"}
    assert pipeline._apply_audio_pick("p1", opts, MULTI) is None
    assert opts["audio_track"] == -1
    assert saved["audio_pick"]["reason"] == "default"


@pytest.mark.parametrize("value,expected", [
    ("ru", "ru"), ("ru-RU", "ru"), ("rus", "ru"), ("Russian", "ru"),
    ("auto", ""), ("", ""), ("q", ""), ("нет", ""),
])
def test_audio_language_code(value, expected):
    assert downloader.audio_language_code(value) == expected


def test_format_selector_prefers_language_and_keeps_fallback():
    fmt = "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[height<=1080]/b"
    out = downloader._prefer_audio_language(fmt, "ru")
    assert "ba[ext=m4a][language^=ru]" in out
    assert out.endswith(fmt)


def test_format_selector_unchanged_without_language():
    fmt = "bv*[height<=1080]+ba/b"
    assert downloader._prefer_audio_language(fmt, "auto") == fmt
    assert downloader._prefer_audio_language(fmt, "") == fmt
    assert downloader._prefer_audio_language(fmt, "xx1") == fmt


def test_audio_language_normalized_in_options():
    opts = pipeline.normalize_options({"audio_lang": "RU-ru"})
    assert opts["audio_lang"] == "ru"
    assert pipeline.normalize_options({"audio_lang": "auto"})["audio_lang"] == "auto"
    assert pipeline.normalize_options({})["audio_lang"] == "auto"
    assert pipeline.normalize_options({"audio_lang": "??"})["audio_lang"] == "auto"


def test_pick_format_prefers_language_audio():
    info = {"formats": [
        {"format_id": "137", "vcodec": "avc1", "acodec": "none", "height": 1080,
         "ext": "mp4"},
        {"format_id": "140", "vcodec": "none", "acodec": "aac", "ext": "m4a",
         "abr": 128, "language": "en"},
        {"format_id": "251", "vcodec": "none", "acodec": "opus", "ext": "webm",
         "abr": 160, "language": "ru"},
    ]}
    fmt, height = downloader._pick_format(info, 1080, "ru")
    assert fmt == "137+251"
    assert height == 1080
    # без предпочтения побеждает m4a с большим битрейтом
    assert downloader._pick_format(info, 1080)[0] == "137+140"
