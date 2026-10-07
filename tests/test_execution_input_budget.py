import tempfile
import unittest
from pathlib import Path

from model_harness.isolated_execution import ExecutionLimits, InputBudgetExceeded, OCIExecutor


class ExecutionInputBudgetTests(unittest.TestCase):
    def test_combined_assets_and_model_are_measured_before_any_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); (base / "asset").write_bytes(b"123456"); (base / "model").write_bytes(b"12345"); target = base / "input"; target.mkdir()
            limits = ExecutionLimits(max_input_bytes=10)
            with self.assertRaises(InputBudgetExceeded) as caught:
                OCIExecutor._snapshot_inputs({"assets/base": base / "asset", "model/weights": base / "model"}, target, limits, None)
            self.assertEqual(caught.exception.required_bytes, 11)
            self.assertEqual(caught.exception.limit_bytes, 10)
            self.assertNotIn(str(base), str(caught.exception))
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(limits.max_input_bytes, 10)

    def test_link_is_rejected_even_when_small_enough(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); (base / "real").write_bytes(b"1"); (base / "link").symlink_to(base / "real"); target = base / "input"; target.mkdir()
            with self.assertRaisesRegex(Exception, "regular file"):
                OCIExecutor._snapshot_inputs({"sample": base / "link"}, target, ExecutionLimits(), None)
            self.assertEqual(list(target.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
