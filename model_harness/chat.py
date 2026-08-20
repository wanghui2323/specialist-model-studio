from __future__ import annotations

from typing import Any

from .errors import HarnessError
from .service import RunService


HELP_ACTIONS = [
    {"label": "开始数字识别实验", "message": "开始数字识别实验"},
    {"label": "查看当前进度", "message": "查看当前进度"},
    {"label": "给出优化建议", "message": "给出优化建议"},
]


class ChatController:
    """Deterministic command layer shared by the standalone UI and adapters."""

    def __init__(self, service: RunService) -> None:
        self.service = service

    def handle(self, message: str, run_id: str | None = None) -> dict[str, Any]:
        text = message.strip()
        if not text:
            return self._reply("请输入一个训练目标或操作。", "help", run_id)
        normalized = text.lower()

        if normalized.startswith("/start") or self._contains(
            text, "开始数字", "开始实验", "训练数字", "新建实验"
        ):
            contract = self.service.registry.get_recipe(
                "digit-classification"
            ).template()
            run_dir = self.service.submit(contract)
            state = self.service.status(run_dir.name)
            return self._reply(
                "数字识别参考实验已经创建。我会保留训练、验证和独立测试边界，并持续更新阶段。",
                "run_started",
                run_dir.name,
                data={"state": state},
                actions=[{"label": "查看进度", "message": "查看当前进度"}],
            )

        if normalized in {"/recipes", "/capabilities"} or self._contains(
            text, "有哪些能力", "支持什么", "可用recipe", "可用 recipe"
        ):
            recipes = self.service.registry.recipe_manifests()
            names = "、".join(item["plugin_id"] for item in recipes)
            return self._reply(
                f"当前可运行的Recipe：{names}。数字分类是教学Recipe；用户图片分类需要先在任务工作台上传数据并确认合同。它们都不等于真实OCR能力。",
                "recipes",
                run_id,
                data={"recipes": recipes},
            )

        if normalized.startswith("/apply") or self._contains(
            text, "批准", "应用策略", "执行策略"
        ):
            selected = self._require_run(run_id)
            strategy_id = self._strategy_id(text)
            if strategy_id is None:
                return self._reply(
                    "请明确批准哪一条策略，例如“批准位移增强”或输入 `/apply add-shift-augmentation`。",
                    "approval_required",
                    selected,
                    data=self.service.result(selected),
                )
            child = self.service.apply_strategy(selected, strategy_id)
            return self._reply(
                "策略已记录为人工批准，并创建了新的子运行；父运行的合同、模型和证据没有被覆盖。",
                "strategy_applied",
                child.name,
                data={
                    "parent_run_id": selected,
                    "child_run_id": child.name,
                    "strategy_id": strategy_id,
                },
                actions=[{"label": "查看子运行", "message": "查看当前进度"}],
            )

        if normalized in {"/strategies", "/optimize"} or self._contains(
            text, "优化建议", "下一步怎么优化", "给出策略", "有哪些策略"
        ):
            selected = self._require_run(run_id)
            result = self.service.result(selected)
            if result["status"] != "completed":
                return self._reply(
                    f"当前运行仍处于 `{result['status']}`，完成独立评测后才会生成有证据的优化建议。",
                    "run_progress",
                    selected,
                    data=result,
                )
            actionable = sum(item["actionable"] for item in result["strategies"])
            return self._reply(
                f"本轮生成了 {len(result['strategies'])} 条建议，其中 {actionable} 条可在批准后创建子运行。请先查看证据、成本和风险。",
                "strategies",
                selected,
                data=result,
            )

        if normalized in {"/cancel", "/stop"} or self._contains(
            text, "取消当前", "停止当前", "先停下"
        ):
            selected = self._require_run(run_id)
            accepted = self.service.cancel(selected, "requested from chat")
            message_text = (
                "取消请求已记录，将在下一个安全阶段边界生效。"
                if accepted
                else "当前运行已经结束，无法再请求取消。"
            )
            return self._reply(
                message_text,
                "cancel_requested" if accepted else "run_terminal",
                selected,
                data=self.service.result(selected),
            )

        if normalized in {"/status", "/progress"} or self._contains(
            text, "当前进度", "训练到哪", "现在到哪", "查看状态"
        ):
            selected = self._require_run(run_id)
            result = self.service.result(selected)
            return self._reply(
                self._status_message(result),
                "run_status",
                selected,
                data=result,
            )

        return self._reply(
            "这一版对话层只执行可审计命令，还不是通用大模型问答。你可以让我开始实验、查看进度、给出策略、批准策略或取消运行。",
            "help",
            run_id,
            actions=HELP_ACTIONS,
        )

    @staticmethod
    def _contains(text: str, *needles: str) -> bool:
        lowered = text.lower()
        return any(needle.lower() in lowered for needle in needles)

    @staticmethod
    def _strategy_id(text: str) -> str | None:
        lowered = text.lower()
        if "add-shift-augmentation" in lowered or "位移" in text:
            return "add-shift-augmentation"
        if "add-noise-augmentation" in lowered or "噪声" in text:
            return "add-noise-augmentation"
        return None

    @staticmethod
    def _status_message(result: dict[str, Any]) -> str:
        status = result["status"]
        if status == "completed":
            metrics = result.get("metrics") or {}
            clean = metrics.get("clean_test", {})
            accuracy = clean.get("accuracy")
            suffix = f"，干净测试集Accuracy为 {accuracy:.4f}" if accuracy else ""
            return f"运行已经完成{suffix}。这仍是教学数据结果，不代表真实业务验收。"
        if status in {"failed", "cancelled", "interrupted"}:
            return f"运行状态为 `{status}`。错误或中断信息：{result.get('error') or '无'}。"
        return f"运行正在 `{status}` 阶段。训练在后台继续，刷新页面不会丢失运行对象。"

    @staticmethod
    def _require_run(run_id: str | None) -> str:
        if not run_id:
            raise HarnessError("请先开始或选择一条运行")
        return run_id

    @staticmethod
    def _reply(
        message: str,
        kind: str,
        run_id: str | None,
        data: dict[str, Any] | None = None,
        actions: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        return {
            "role": "assistant",
            "kind": kind,
            "message": message,
            "run_id": run_id,
            "data": data or {},
            "actions": actions or [],
        }
