"""Повтор распознавания без VAD, когда фильтр отсёк пение."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from vertcut import transcribe


class VadFallbackTest(unittest.TestCase):
    def test_retries_without_vad_when_first_pass_empty(self):
        calls = []

        def fake_consume(model, path, language, use_vad, offset, total, progress, batched=False, prompt=None):
            calls.append(use_vad)
            if use_vad:
                return [], None
            return [{"text": "la la la", "words": []}], None

        with mock.patch.object(transcribe, "_consume", fake_consume):
            parts, _info = transcribe._transcribe_span(
                None, Path("x.wav"), None, 0.0, 10.0, None)

        self.assertEqual(calls, [True, False])
        self.assertEqual(len(parts), 1)

    def test_keeps_vad_result_when_not_empty(self):
        calls = []

        def fake_consume(model, path, language, use_vad, offset, total, progress, batched=False, prompt=None):
            calls.append(use_vad)
            return [{"text": "hello"}], None

        with mock.patch.object(transcribe, "_consume", fake_consume):
            parts, _info = transcribe._transcribe_span(
                None, Path("x.wav"), None, 0.0, 10.0, None)

        self.assertEqual(calls, [True])
        self.assertEqual(parts[0]["text"], "hello")

    def test_falls_back_when_vad_crashes(self):
        calls = []

        def fake_consume(model, path, language, use_vad, offset, total, progress, batched=False, prompt=None):
            calls.append(use_vad)
            if use_vad:
                raise RuntimeError("onnxruntime failed to load vad model")
            return [{"text": "ok"}], None

        with mock.patch.object(transcribe, "_consume", fake_consume):
            parts, _info = transcribe._transcribe_span(
                None, Path("x.wav"), None, 0.0, 10.0, None)

        self.assertEqual(calls, [True, False])
        self.assertEqual(parts[0]["text"], "ok")


class PromptEchoTest(unittest.TestCase):
    def test_prompt_text_is_detected(self):
        self.assertTrue(transcribe._prompt_echo(
            "Субтитры, вертикальные клипы, подкаст, интервью"))

    def test_real_lyrics_are_kept(self):
        self.assertFalse(transcribe._prompt_echo("Girls, big girls, if we do what we want"))
        self.assertFalse(transcribe._prompt_echo("Почему люди боятся начать своё дело"))


if __name__ == "__main__":
    unittest.main()
