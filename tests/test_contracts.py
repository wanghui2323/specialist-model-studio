from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from model_harness.contracts import (
    ApprovalDecision,
    ApprovalDecisionIntegrityError,
    ContractError,
    ContractRevision,
    ContractRevisionIntegrityError,
    validate_contract,
)
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

    def test_contract_revision_and_approval_are_digest_bound(self) -> None:
        snapshot = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        snapshot["task_id"] = "contract-task"
        revision = ContractRevision.create(
            contract_revision_id="contract-revision-unit",
            task_id="contract-task",
            spec_revision_id="contract-task:spec:r1",
            dataset_id="dataset-unit",
            dataset_fingerprint_sha256="a" * 64,
            contract_snapshot=snapshot,
            created_at_utc="2026-08-26T00:00:00+00:00",
        ).to_dict()
        approval = ApprovalDecision.create(
            approval_decision_id="approval-decision-unit",
            revision=revision,
            actor="unit-user",
            checkpoint_id="checkpoint:unit",
            confirmations={
                "data_authorized": True,
                "labels_reviewed": True,
                "gates_reviewed": True,
            },
            created_at_utc="2026-08-26T00:01:00+00:00",
        ).to_dict()
        self.assertEqual(
            approval["contract_revision_id"], revision["contract_revision_id"]
        )
        self.assertEqual(approval["contract_sha256"], revision["contract_sha256"])

    def test_immutable_revision_and_approval_detect_tampering(self) -> None:
        snapshot = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        snapshot["task_id"] = "contract-task"
        revision = ContractRevision.create(
            contract_revision_id="contract-revision-tamper",
            task_id="contract-task",
            spec_revision_id="contract-task:spec:r1",
            dataset_id="dataset-unit",
            dataset_fingerprint_sha256="b" * 64,
            contract_snapshot=snapshot,
        ).to_dict()
        tampered_revision = deepcopy(revision)
        tampered_revision["dataset_id"] = "dataset-other"
        with self.assertRaises(ContractRevisionIntegrityError):
            ContractRevision.from_record(tampered_revision)

        approval = ApprovalDecision.create(
            approval_decision_id="approval-decision-tamper",
            revision=revision,
            actor="unit-user",
            checkpoint_id="checkpoint:unit",
            confirmations={
                "data_authorized": True,
                "labels_reviewed": True,
                "gates_reviewed": True,
            },
        ).to_dict()
        tampered_approval = deepcopy(approval)
        tampered_approval["checkpoint_id"] = "checkpoint:other"
        with self.assertRaises(ApprovalDecisionIntegrityError):
            ApprovalDecision.from_record(tampered_approval)


if __name__ == "__main__":
    unittest.main()
