from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.worker import ui_runner


class UIRunnerTestCase(unittest.TestCase):
    def test_ui_runner_changes_to_ui_dir_before_exec(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ui_runner_test_", dir="/tmp") as temp_dir:
            workspace = Path(temp_dir)
            ui_dir = workspace / "ui"
            ui_dir.mkdir()
            (ui_dir / "node_modules").mkdir()

            with (
                patch.object(sys, "argv", ["ui_runner", "--workspace", str(workspace)]),
                patch.object(ui_runner, "load_settings", return_value=SimpleNamespace(api_host="0.0.0.0", api_port=8000)),
                patch.object(ui_runner.shutil, "which", return_value="/usr/local/bin/npm"),
                patch.object(ui_runner.os, "chdir") as mock_chdir,
                patch.object(ui_runner.os, "execvpe", side_effect=SystemExit(0)) as mock_execvpe,
            ):
                with self.assertRaises(SystemExit):
                    ui_runner.main()

            mock_chdir.assert_called_once_with(ui_dir.resolve())
            mock_execvpe.assert_called_once()
            exec_path, exec_args, exec_env = mock_execvpe.call_args.args
            self.assertEqual(exec_path, "/usr/local/bin/npm")
            self.assertEqual(exec_args, ["/usr/local/bin/npm", "run", "dev", "--", "--host", "0.0.0.0"])
            self.assertEqual(exec_env["PWD"], str(ui_dir.resolve()))


if __name__ == "__main__":
    unittest.main()
