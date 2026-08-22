from __future__ import annotations

import unittest

from model_harness.optimization import (
    attach_provenance,
    propose_strategies_with_provenance,
)
from model_harness.plugin_api import StrategyProposal


def proposal(evidence: dict) -> StrategyProposal:
    return StrategyProposal(
        strategy_id="adjust",
        title="adjust",
        hypothesis="fixture",
        changes=("change",),
        expected_effect="fixture",
        estimated_cost="low",
        risk="low",
        requires_approval=True,
        actionable=True,
        evidence=evidence,
    )


class TestMetricPlugin:
    def propose_strategies(self, metrics, contract):
        score = metrics["clean_test"]["accuracy"]
        shifted = metrics.get("stress_tests", {}).get("shift", {}).get("accuracy")
        return [proposal({"clean_test_accuracy": score, "test_shift": shifted})]


class ValidationMetricPlugin:
    def propose_strategies(self, metrics, contract):
        candidates = metrics["validation_candidates"]
        score = max(value["macro_f1"] for value in candidates.values())
        return [proposal({"validation_macro_f1": score})]


class OptimizationProvenanceTests(unittest.TestCase):
    def test_test_metric_access_and_embedded_values_are_marked(self) -> None:
        strategies, provenance = propose_strategies_with_provenance(
            TestMetricPlugin(),
            {
                "clean_test": {"accuracy": 0.7},
                "stress_tests": {"shift": {"accuracy": 0.4}},
            },
            {},
        )
        serialized = attach_provenance(strategies[0], provenance)

        self.assertTrue(provenance["uses_test_evidence"])
        self.assertIn("clean_test", provenance["test_metric_paths"])
        self.assertIn("stress_tests", provenance["test_metric_paths"])
        self.assertIn(
            "clean_test_accuracy", provenance["test_evidence_fields"]
        )
        self.assertTrue(
            serialized["evidence_provenance"]["uses_test_evidence"]
        )
        self.assertEqual(
            serialized["evidence_provenance"]["policy"],
            "child_run_must_be_marked_test_contaminated",
        )

    def test_validation_only_strategy_remains_uncontaminated(self) -> None:
        strategies, provenance = propose_strategies_with_provenance(
            ValidationMetricPlugin(),
            {
                "validation_candidates": {
                    "a": {"macro_f1": 0.72},
                    "b": {"macro_f1": 0.81},
                }
            },
            {},
        )
        serialized = attach_provenance(strategies[0], provenance)

        self.assertFalse(provenance["uses_test_evidence"])
        self.assertEqual(provenance["test_metric_paths"], [])
        self.assertFalse(
            serialized["evidence_provenance"]["uses_test_evidence"]
        )
        self.assertEqual(
            serialized["evidence_provenance"]["policy"],
            "validation_or_training_evidence_only",
        )


if __name__ == "__main__":
    unittest.main()
