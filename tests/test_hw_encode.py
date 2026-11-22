"""Выбор аппаратного энкодера и его аргументов."""
from __future__ import annotations

import os
import subprocess
import unittest
from unittest import mock

from vertcut import render


class HardwareEncoderTest(unittest.TestCase):
    def setUp(self):
        render._HW_CACHE.clear()

    def tearDown(self):
        render._HW_CACHE.clear()

    def test_finds_nvenc(self):
        proc = subprocess.CompletedProcess([], 0, " V....D h264_nvenc ...", "")
        with mock.patch.object(render, "run", return_value=proc), \
             mock.patch.dict(os.environ, {"VERTCUT_HW_ENCODE": "auto"}):
            self.assertEqual(render.hw_encoder(), "h264_nvenc")

    def test_forced_cpu(self):
        with mock.patch.dict(os.environ, {"VERTCUT_HW_ENCODE": "0"}):
            self.assertIsNone(render.hw_encoder())

    def test_nvenc_args(self):
        args = render._hw_args("h264_nvenc", 20)
        self.assertEqual(args[:2], ["-c:v", "h264_nvenc"])
        self.assertIn("-cq", args)
        self.assertIn("20", args)


if __name__ == "__main__":
    unittest.main()
