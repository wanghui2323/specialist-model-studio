from __future__ import annotations

import tempfile
import unittest

from model_harness.chat import ChatController
from model_harness.errors import HarnessError
from model_harness.service import RunService


class ChatControllerTests(unittest.TestCase):
    def test_conversation_run_creation_commands_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with RunService(temp_dir, recover=False) as service:
                chat = ChatController(service)
                with self.assertRaisesRegex(HarnessError, "task-owned"):
                    chat.handle("开始数字识别实验")
                with self.assertRaisesRegex(HarnessError, "当前训练任务"):
                    chat.handle("批准位移增强", run_id="parent")
                with self.assertRaisesRegex(HarnessError, "task-owned"):
                    chat.handle("取消当前训练", run_id="parent")
                self.assertEqual(service.list_runs(), [])

    def test_unknown_message_is_transparently_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with RunService(temp_dir, recover=False) as service:
                response = ChatController(service).handle("帮我写一首诗")
        self.assertEqual(response["kind"], "help")
        self.assertIn("不是通用大模型问答", response["message"])


if __name__ == "__main__":
    unittest.main()
