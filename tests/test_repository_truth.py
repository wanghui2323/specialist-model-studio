from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class RepositoryTruthTests(unittest.TestCase):
    def test_ci_jobs_match_the_release_contract_check_names(self) -> None:
        gates = json.loads(
            (ROOT / "acceptance" / "v0.7-gates.json").read_text(
                encoding="utf-8"
            )
        )
        workflow = yaml.safe_load(
            (ROOT / ".github" / "workflows" / "ci.yml").read_text(
                encoding="utf-8"
            )
        )
        required = set(gates["release_contract"]["required_check_names"])
        jobs = workflow["jobs"]

        self.assertEqual(set(jobs), required)
        self.assertEqual({job["name"] for job in jobs.values()}, required)

    def test_published_skill_preserves_v07_execution_boundary(self) -> None:
        skill = (ROOT / "skills" / "train-small-model" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("blocked_environment", skill)
        self.assertIn("declarative audio `RecipeSpec`", skill)
        self.assertIn("Do not run external or Agent-generated Python", skill)
        self.assertNotIn("Run external or Agent-generated training code", skill)
        self.assertNotIn("primary v0.4 surface", skill)

    def test_readme_distinguishes_builtin_and_dynamic_recipes(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("两个内置的用户数据 Recipe", readme)
        self.assertIn("音频关键词分类（动态注册）", readme)
        self.assertIn(".[server,test]", readme)
        self.assertIn("npm ci --prefix integrations/deepseek-harness", readme)
        self.assertIn("它不冒充真实 PID 重启", readme)

    def test_loop_ledger_separates_local_verification_from_release(self) -> None:
        ledger = json.loads(
            (
                ROOT
                / "plans"
                / "v0.7-real-training-beta"
                / "loop-tasks.json"
            ).read_text(encoding="utf-8")
        )
        statuses = {
            loop["loop_id"]: loop["status"] for loop in ledger["loops"]
        }
        self.assertEqual(statuses["L0"], "accepted")
        self.assertEqual(
            {statuses[f"L{index}"] for index in range(1, 6)},
            {"verified"},
        )
        self.assertTrue(
            all(
                not task.get("blocked_by")
                for loop in ledger["loops"]
                for task in loop["tasks"]
            )
        )
        self.assertEqual(
            ledger["gate"],
            "macro-loop-local-beta-verified-github-release-pending",
        )

        requirements = (
            ROOT / "plans" / "v0.7-real-training-beta" / "requirements.md"
        ).read_text(encoding="utf-8")
        self.assertIn("最终用户验收仍待确认", requirements)
        self.assertIn("未创建 GitHub Tag / Release", requirements)

        l5_contract = (
            ROOT / "plans" / "v0.7-real-training-beta" / "l5-acceptance-contract.md"
        ).read_text(encoding="utf-8")
        self.assertIn("内容寻址包缓存", l5_contract)
        self.assertIn("全新的源码目录、`.venv`、运行对象", l5_contract)


if __name__ == "__main__":
    unittest.main()
