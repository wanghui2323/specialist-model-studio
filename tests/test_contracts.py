from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from model_harness.contracts import ContractError, validate_contract
from model_harness.templates import DIGIT_CLASSIFICATION_TEMPLATE


ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_template_is_valid(self) -> None:
        validate_contract(deepcopy(DIGIT_CLASSIFICATION_TEMPLATE))

    def test_repository_example_matches_template(self) -> None:
        example = json.loads(
            (
                ROOT
                / "examples"
                / "digit-classification"
                / "task_contract.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(example, DIGIT_CLASSIFICATION_TEMPLATE)

    def test_split_must_sum_to_one(self) -> None:
        contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        contract["dataset"]["split"]["test"] = 0.30
        with self.assertRaisesRegex(ContractError, "must equal 1.0"):
            validate_contract(contract)

    def test_candidate_count_cannot_exceed_budget(self) -> None:
        contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        contract["compute_budget"]["max_candidate_models"] = 2
        with self.assertRaisesRegex(ContractError, "exceeds compute budget"):
            validate_contract(contract)

    def test_optimization_cannot_bypass_human_approval(self) -> None:
        contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        contract["optimization"]["require_approval"] = False
        with self.assertRaisesRegex(ContractError, "require_approval=true"):
            validate_contract(contract)


if __name__ == "__main__":
    unittest.main()
