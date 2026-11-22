"""Датчики нагрузки и выбор папки проектов."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vertcut import config, sysmon


class NvidiaParseTest(unittest.TestCase):
    def test_full_line(self):
        data = sysmon.parse_nvidia_smi(
            "NVIDIA GeForce RTX 5070 Ti, 2, 37, 3691, 16303, 22, 3\n")
        self.assertEqual(data["name"], "NVIDIA GeForce RTX 5070 Ti")
        self.assertEqual(data["util"], 2.0)
        self.assertEqual(data["temp"], 37.0)
        self.assertEqual(data["mem_used_mb"], 3691.0)
        self.assertEqual(data["mem_total_mb"], 16303.0)
        self.assertAlmostEqual(data["mem_percent"], 22.6, places=1)
        self.assertEqual(data["encoder"], 22.0)
        self.assertEqual(data["decoder"], 3.0)

    def test_unknown_values_become_none(self):
        data = sysmon.parse_nvidia_smi("NVIDIA GPU, [N/A], N/A, 100, 1000")
        self.assertIsNone(data["util"])
        self.assertIsNone(data["temp"])
        self.assertEqual(data["mem_percent"], 10.0)

    def test_empty_or_broken_output(self):
        self.assertIsNone(sysmon.parse_nvidia_smi(""))
        self.assertIsNone(sysmon.parse_nvidia_smi("no comma separated fields"))


class ProjectsDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _resolve(self, env=None):
        with mock.patch.dict(os.environ, env or {}, clear=True):
            return config.resolve_projects_dir(self.data)

    def test_default_is_under_data_dir(self):
        self.assertEqual(self._resolve(), (self.data / "projects").resolve())

    def test_env_absolute_path(self):
        target = self.data / "other" / "projects"
        self.assertEqual(
            self._resolve({"VERTCUT_PROJECTS": str(target)}), target.resolve())

    def test_env_relative_path_is_under_data_dir(self):
        self.assertEqual(
            self._resolve({"VERTCUT_PROJECTS": "external/projects"}),
            (self.data / "external" / "projects").resolve())

    def test_marker_file_for_built_app(self):
        target = self.data / "E_drive" / "projects"
        (self.data / "projects_dir.txt").write_text(str(target), encoding="utf-8")
        self.assertEqual(self._resolve(), target.resolve())


if __name__ == "__main__":
    unittest.main()
