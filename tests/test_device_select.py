"""Выбор устройства распознавания: одна сборка должна работать везде."""
from __future__ import annotations

import unittest
from unittest import mock

from vertcut import transcribe


class DeviceCandidatesTest(unittest.TestCase):
    def test_no_gpu_falls_back_to_cpu(self):
        with mock.patch.object(transcribe, "_cuda_available", return_value=False):
            self.assertEqual(transcribe._device_candidates(False), [("cpu", "int8")])
            self.assertEqual(transcribe._device_candidates(True), [("cpu", "int8")])

    def test_gpu_prefers_float16(self):
        with mock.patch.object(transcribe, "_cuda_available", return_value=True):
            for long_audio in (False, True):
                candidates = transcribe._device_candidates(long_audio)
                self.assertEqual(candidates[0], ("cuda", "float16"))
                self.assertEqual(candidates[-1], ("cpu", "int8"))

    def test_explicit_device_wins(self):
        with mock.patch.object(transcribe, "WHISPER_DEVICE", "cpu"):
            self.assertEqual(transcribe._device_candidates(False), [("cpu", "int8")])
        with mock.patch.object(transcribe, "WHISPER_DEVICE", "cuda"):
            self.assertEqual(transcribe._device_candidates(False)[0][0], "cuda")

    def test_gpu_present_but_libs_missing_is_explained(self):
        transcribe._CUDA_STATE.clear()
        with mock.patch.object(transcribe, "_setup_cuda_dlls", lambda: None), \
             mock.patch.object(transcribe, "_nvidia_gpu_present", return_value=True):
            import ctranslate2

            with mock.patch.object(ctranslate2, "get_cuda_device_count", lambda: 0):
                info = transcribe.device_info()
        transcribe._CUDA_STATE.clear()
        self.assertEqual(info["device"], "cpu")
        self.assertTrue(info["gpu_present"])
        self.assertIn("enable_cuda", info["note"])


if __name__ == "__main__":
    unittest.main()
