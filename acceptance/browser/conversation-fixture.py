"""Local-only conversation UI fixture. Not a real model or release acceptance.

Runs the real API, evidence store and frontend with a deterministic DSH transport.
Start with: python acceptance/browser/conversation-fixture.py --runs-dir /tmp/... --port 8876
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
from test_multi_agent_runtime import FakeDshClient, FakeEventHub
from model_harness.multi_agent import DshMultiAgentRuntime
from model_harness.server import create_app
import uvicorn


class FixtureClient(FakeDshClient):
    def emit(self, session, kind, data):
        history = self.sessions[session]["events"]
        history.append({"event": {"seq": len(history) + 1,
            "time": datetime.now(timezone.utc).isoformat(), "type": kind, "data": data}})

    def call(self, method, payload):
        result = super().call(method, payload)
        session = payload.get("sessionId")
        if method == "session.prompt":
            instruction = payload["content"][0]["text"]
            self.emit(session, "user/message", {"source": {"kind": "user"}, "content": payload["content"]})
            if "CHECKPOINT_DISCUSSION:" in instruction:
                message = instruction.split("USER_MESSAGE:\n")[-1]
                text = "【受控回归夹具，不是真实模型回答】\n\n已收到你的追问：" + message
                text += "\n\n当前检查点已暂缓，没有批准执行，也没有提交数据答案。"
                text += "\n\n可以先准备以下内容：\n- 输入字段的含义\n- 期望预测的目标\n- 不同记录之间的区别"
                text += "\n\n" + "格式示例仅用于解释；实际数据仍需独立体检，结果仍需证据。" * 32
                text += "\n\n完整回答末尾：请按你的节奏继续讨论。"
                self.emit(session, "assistant/message", {"message": {"content": [{"type": "text", "text": text}]}})
                self.emit(session, "turn/end", {"reason": {"kind": "completed"}})
                self.sessions[session]["running"] = False
        elif method == "session.cancel":
            self.emit(session, "turn/end", {"reason": {"kind": "interrupted"}})
        return result


def build_fixture(runs_dir):
    client, events = FixtureClient(), FakeEventHub()
    def build(**kwargs):
        return DshMultiAgentRuntime(workspace_root=kwargs["workspace_root"], client=client,
            events=events, cwd=ROOT, background_actions_provider=kwargs["background_actions_provider"],
            background_actions_canceller=kwargs["background_actions_canceller"])
    with patch("model_harness.server.build_dsh_multi_agent_runtime", side_effect=build):
        app = create_app(runs_dir)
    workspace = app.state.training_workspace
    runtime = app.state.conversation_runtime
    for kind in ("question", "approval"):
        task = workspace.create_task("回归夹具 · " + kind, "根据每条独立房屋记录的面积和房龄预测价格",
                                     recipe_id="tabular-regression")
        task_id = task["task_id"]
        session = runtime.prompt(task_id, task["name"], "【受控夹具】检查连续对话")
        call_id = "fixture-" + kind
        tool = "ask_user_question" if kind == "question" else "model_harness_confirm_contract"
        client.emit(session, "tool/call", {"callId": call_id, "name": tool,
                    "agentId": "training_orchestrator", "input": {"task_id": task_id}})
        events.pending[session] = [{"kind": kind, "rpc_id": "rpc-" + kind,
            "approval_id": call_id, "call_id": call_id, "received_at": datetime.now(timezone.utc).timestamp(),
            "tool_name": tool, "questions": [{"id": "data_upload", "header": "准备数据", "question": "请选择 CSV 数据"}]}]
        runtime.conversation(task_id)
        print(f"FIXTURE {kind}: /app?task={task_id}", flush=True)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-dir", required=True)
    parser.add_argument("--port", type=int, default=8876)
    args = parser.parse_args()
    uvicorn.run(build_fixture(args.runs_dir), host="127.0.0.1", port=args.port)
