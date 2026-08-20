from __future__ import annotations

import tempfile
import unittest

from model_harness.chat import ChatController
from model_harness.service import RunService


class ChatControllerTests(unittest.TestCase):
    def test_conversation_starts_run_and_applies_approved_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with RunService(temp_dir, recover=False) as service:
                chat = ChatController(service)
                started = chat.handle("开始数字识别实验")
                parent_id = started["run_id"]
                self.assertEqual(started["kind"], "run_started")
                service.wait(parent_id, timeout=30)

                status = chat.handle("查看当前进度", run_id=parent_id)
                self.assertEqual(status["data"]["status"], "completed")

                strategies = chat.handle("给出优化建议", run_id=parent_id)
                self.assertEqual(strategies["kind"], "strategies")
                strategy_ids = {
                    item["strategy_id"] for item in strategies["data"]["strategies"]
                }
                self.assertIn("add-shift-augmentation", strategy_ids)

                approved = chat.handle("批准位移增强", run_id=parent_id)
                child_id = approved["run_id"]
                service.wait(child_id, timeout=30)
                child = service.result(child_id)

            self.assertEqual(approved["kind"], "strategy_applied")
            self.assertEqual(child["parent_run_id"], parent_id)
            self.assertEqual(child["status"], "completed")

    def test_unknown_message_is_transparently_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with RunService(temp_dir, recover=False) as service:
                response = ChatController(service).handle("帮我写一首诗")
        self.assertEqual(response["kind"], "help")
        self.assertIn("不是通用大模型问答", response["message"])


if __name__ == "__main__":
    unittest.main()
