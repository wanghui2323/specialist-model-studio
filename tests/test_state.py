from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from model_harness.state import RunState


class RunStateTests(unittest.TestCase):
    def test_cancellation_is_persisted_as_versioned_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "cancel-me"
            run_dir.mkdir()
            state = RunState(
                run_dir,
                task_id="task",
                run_id="cancel-me",
                plugin_id="digit-classification",
            )
            state.transition("queued")
            self.assertTrue(state.request_cancel("test request"))
            state.cancel("test request")

            records = [
                json.loads(line)
                for line in state.events_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(state.status, "cancelled")
            self.assertEqual(
                [record["seq"] for record in records],
                list(range(1, len(records) + 1)),
            )
            self.assertIn("run.cancel_requested", {item["type"] for item in records})
            self.assertIn("run.cancelled", {item["type"] for item in records})

    def test_stale_worker_event_cannot_erase_concurrent_cancel_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "concurrent-cancel"
            run_dir.mkdir()
            worker = RunState(
                run_dir,
                task_id="task",
                run_id="concurrent-cancel",
                plugin_id="digit-classification",
            )
            worker.transition("queued")
            worker.transition("preflight")
            worker.transition("training")
            canceller = RunState.load(run_dir)

            self.assertTrue(canceller.request_cancel("stop agent cascade"))
            worker.event("training.worker_returned", {"ok": True})

            persisted = RunState.load(run_dir)
            self.assertTrue(persisted.cancel_requested)
            self.assertEqual(
                persisted.data["cancel_reason"],
                "stop agent cascade",
            )
            records = [
                json.loads(line)
                for line in persisted.events_path.read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(
                [record["seq"] for record in records],
                list(range(1, len(records) + 1)),
            )


if __name__ == "__main__":
    unittest.main()
