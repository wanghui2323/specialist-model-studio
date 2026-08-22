from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryTruthTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
