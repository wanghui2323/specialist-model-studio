"""Policy-delivery regressions; real-model dialogue is verified separately."""
from __future__ import annotations

import unittest
from pathlib import Path

from model_harness.multi_agent import DshMultiAgentRuntime


class ConsultationInstructionTests(unittest.TestCase):
    def instruction(self, kind: str, message: str) -> str:
        return DshMultiAgentRuntime._root_instruction(
            task_id="task-route-policy",
            agent_run_id="agent-run-route-policy",
            current_spec_revision=2,
            record_type=kind,
            user_message=message,
        )

    def test_host_preserves_user_input_without_duplicating_consultation_policy(self) -> None:
        for kind in ("conversation_draft", "training_task"):
            for message in ("我想训练一个我自己的语音tts", "我明确想从零训练并学习训练过程", "没有现成资料，请给出准备建议"):
                with self.subTest(kind=kind, message=message):
                    prompt = self.instruction(kind, message)
                    host, delimiter, user_message = prompt.partition("USER_MESSAGE:\n")
                    self.assertEqual(delimiter, "USER_MESSAGE:\n")
                    self.assertEqual(user_message, message)
                    self.assertIn("共享咨询策略", host)
                    self.assertIn("身份、事实源和执行授权约束", host)
                    for retired_patch in ("自己的声音", "参考录音克隆", "三条路线", "150到300", "三条简短路线"):
                        self.assertNotIn(retired_patch, host)
                    self.assertTrue(prompt.endswith("USER_MESSAGE:\n" + message))

    def test_route_guidance_preserves_intake_and_execution_identity_boundaries(self) -> None:
        intake = self.instruction("conversation_draft", "我想做一个模型")
        self.assertIn("CONVERSATION_MODE: INTAKE", intake)
        self.assertIn('EXACT_CONVERSATION_ID_JSON: "task-route-policy"', intake)
        self.assertIn("model_harness_promote_conversation", intake)
        self.assertIn("只读调用 model_harness_get_local_resources", intake)
        self.assertIn("不创建任务或授权执行", intake)
        self.assertIn("材料检查不要求先建立训练任务", intake)
        for tool in ("model_harness_get_conversation", "model_harness_list_materials", "model_harness_get_material"):
            self.assertIn(tool, intake)
        self.assertIn("不得调用 model_harness_create_task", intake)
        bound = self.instruction("training_task", "我要基于已有权重微调")
        self.assertIn('EXACT_TASK_ID_JSON: "task-route-policy"', bound)
        self.assertIn("只有已验证 Recipe 与 Adapter 可创建 Run", bound)
        self.assertIn("model_harness_authorize_task_run_start", bound)
        self.assertIn("目标或数据变化后旧确认必须失效", bound)


if __name__ == "__main__":
    unittest.main()

class FreshSpecialistPresetSyntaxTest(unittest.TestCase):
    def test_operator_route_expressions_are_valid_yaml_and_apply_to_each_delegate(self):
        import yaml
        class Loader(yaml.SafeLoader):pass
        Loader.add_constructor('tag:yaml.org,2002:js',lambda loader,node:loader.construct_scalar(node))
        root=Path(__file__).resolve().parents[1]
        preset=yaml.load((root/'integrations/deepseek-harness/presets/model-training/agent.cordis.yml').read_text(),Loader=Loader)
        group=next(item for item in preset if item['id']=='delegation')
        delegates=[item for item in group['config'] if item['name']=='@deepseek-ai/dsh-tool-subagent']
        self.assertEqual(len(delegates),5)
        for item in delegates:
            expression=item['config']['agentOptions']
            self.assertIn('MODEL_HARNESS_AGENT_PROVIDER',expression)
            self.assertIn('MODEL_HARNESS_AGENT_MODEL',expression)
            self.assertNotIn('deepseek-official',expression)
