import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from model_harness.execution_runtime import execution_root, execution_runtime_config
from model_harness.io_utils import write_json


class ExecutionRuntimeConfigTests(unittest.TestCase):
    def test_shared_operator_path_overrides_per_run_default_for_every_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / "vm-shared"
            with patch.dict(os.environ, {"MODEL_HARNESS_ISOLATED_ROOT": ""}), patch("model_harness.execution_runtime.execution_runtime_config", return_value={"isolated_root": str(shared)}):
                roots = [execution_root(Path(directory) / phase) for phase in ("qualify", "train", "evaluate", "predict")]
            self.assertEqual(roots, [shared.resolve()] * 4)

    def test_explicit_and_environment_precedence_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with patch.dict(os.environ, {"MODEL_HARNESS_ISOLATED_ROOT": str(base / "env")}), patch("model_harness.execution_runtime.execution_runtime_config", return_value={"isolated_root": str(base / "config")}):
                self.assertEqual(execution_root(base / "default"), (base / "env").resolve())
                self.assertEqual(execution_root(base / "default", explicit=base / "explicit"), (base / "explicit").resolve())
            self.assertEqual(list(base.iterdir()), [])

    def test_symlinked_config_is_not_read(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); write_json(base / "original.json", {"isolated_root": "private"}); (base / "linked.json").symlink_to(base / "original.json")
            self.assertEqual(execution_runtime_config(base / "linked.json"), {})


if __name__ == "__main__":
    unittest.main()
