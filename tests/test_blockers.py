from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from model_harness.blockers import BlockerStore
from model_harness.errors import ContractError
from model_harness.io_utils import read_json, write_json


class BlockerStoreTests(unittest.TestCase):
    def test_blocker_and_resolution_are_append_only_and_restart_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BlockerStore(temporary)
            blocker = store.append(
                "task-1",
                stage="source_resolution",
                code="github_source_not_found",
                message="仓库或版本不存在",
                retry_action="edit_source_reference",
                details={"provider": "github"},
            )
            duplicate = store.append(
                "task-1",
                stage="source_resolution",
                code="github_source_not_found",
                message="不同展示文本不会改写原始事实",
                retry_action="edit_source_reference",
                details={"provider": "github"},
            )
            self.assertEqual(duplicate, blocker)
            self.assertEqual(len(store.list("task-1", active_only=True)), 1)
            resolution = store.resolve(
                "task-1",
                blocker["blocker_id"],
                action="source_resolved",
                related_object_type="SourceResolution",
                related_object_id="resolution-1",
            )
            self.assertEqual(resolution["blocker_digest"], blocker["content_digest"])
            self.assertEqual(store.list("task-1", active_only=True), [])
            restarted = BlockerStore(temporary)
            self.assertFalse(restarted.list("task-1")[0]["active"])

    def test_tamper_and_unsafe_values_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BlockerStore(temporary)
            blocker = store.append(
                "task-1",
                stage="resource_fit",
                code="insufficient_ram",
                message="内存不足",
                retry_action="review_alternatives",
            )
            path = (
                Path(temporary)
                / "tasks"
                / "task-1"
                / "blockers"
                / "evidence"
                / f"{blocker['blocker_id']}.json"
            )
            value = read_json(path)
            value["message"] = "tampered"
            write_json(path, value)
            with self.assertRaisesRegex(ContractError, "digest mismatch"):
                store.list("task-1")
            with self.assertRaises(ContractError):
                store.append(
                    "../escape",
                    stage="resource_fit",
                    code="bad",
                    message="bad",
                    retry_action="bad",
                )


if __name__ == "__main__":
    unittest.main()
