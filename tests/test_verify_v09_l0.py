from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.verify_v09_l0 import (
    NODE_REGRESSION_COMMAND,
    NODE_REGRESSION_WORKDIR,
    PYTHON_REGRESSION_COMMAND,
    STATIC_L0_PATHS,
    _regression_passed,
    validate_l0_transition,
    validate_ledger_for_l0_gate,
)


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "plans" / "v0.9-universal-byom" / "loop-tasks.json"
EXPECTED_STATIC_PATHS = (
    "AGENTS.md",
    "plans/v0.9-universal-byom/requirements.md",
    "plans/v0.9-universal-byom/object-model.md",
    "plans/v0.9-universal-byom/closure-matrix.md",
    "plans/v0.9-universal-byom/acceptance-contract.md",
    "plans/v0.9-universal-byom/baseline-evidence.json",
    "scripts/check_v09_status.py",
    "scripts/verify_v09_l0.py",
)


def _regression_record(
    *,
    command: str,
    total: int,
    workdir: str | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "command": command,
        "exit_code": 0,
        "passed": total,
        "total": total,
        "report_sha256": "a" * 64,
    }
    if workdir is not None:
        value["workdir"] = workdir
    return value


class VerifyV09L0LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_current_implemented_snapshot_is_valid_but_not_l0_verified(self) -> None:
        loops = validate_ledger_for_l0_gate(self.ledger, require_passed=False)
        self.assertEqual(
            [(item["loop_id"], item["status"]) for item in loops],
            [
                ("L0", "implemented"),
                ("L1", "implemented"),
                ("L2", "implemented"),
                ("L3", "planned"),
                ("L4", "planned"),
                ("L5", "planned"),
            ],
        )
        with self.assertRaisesRegex(AssertionError, "requires verified or accepted"):
            validate_ledger_for_l0_gate(self.ledger)

    def test_current_l0_can_stay_verified_while_later_loops_advance(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["loops"][0]["status"] = "verified"
        for task in ledger["loops"][0]["tasks"]:
            task["status"] = "verified"
        ledger["loops"][1]["status"] = "verified"
        for task in ledger["loops"][1]["tasks"]:
            task["status"] = "verified"
        ledger["loops"][2]["status"] = "accepted"

        loops = validate_ledger_for_l0_gate(ledger)

        self.assertEqual(loops[1]["status"], "verified")
        self.assertEqual(loops[2]["status"], "accepted")

    def test_accepted_l0_preserves_verified_machine_tasks(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["loops"][0]["status"] = "accepted"
        for task in ledger["loops"][0]["tasks"]:
            task["status"] = "verified"
        validate_ledger_for_l0_gate(ledger)

    def test_unknown_lifecycle_state_fails_closed(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["loops"][2]["status"] = "done"
        with self.assertRaisesRegex(AssertionError, "unsupported lifecycle"):
            validate_ledger_for_l0_gate(ledger, require_passed=False)

    def test_l0_task_inventory_rejects_duplicates_and_wrong_states(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["loops"][0]["status"] = "verified"
        for task in ledger["loops"][0]["tasks"]:
            task["status"] = "verified"
        ledger["loops"][0]["tasks"].append(
            copy.deepcopy(ledger["loops"][0]["tasks"][0])
        )
        with self.assertRaisesRegex(AssertionError, "task inventory"):
            validate_ledger_for_l0_gate(ledger)

        ledger["loops"][0]["tasks"] = ledger["loops"][0]["tasks"][:3]
        ledger["loops"][0]["tasks"][0]["status"] = "implemented"
        with self.assertRaisesRegex(AssertionError, "must be verified"):
            validate_ledger_for_l0_gate(ledger)

    def test_static_hash_and_owned_scope_is_exactly_eight_paths(self) -> None:
        self.assertEqual(STATIC_L0_PATHS, EXPECTED_STATIC_PATHS)

    def test_python_regression_requires_full_exact_attestation(self) -> None:
        good = _regression_record(command=PYTHON_REGRESSION_COMMAND, total=337)
        self.assertTrue(
            _regression_passed(
                good,
                expected_command=PYTHON_REGRESSION_COMMAND,
                minimum_total=330,
            )
        )
        mutations = (
            {**good, "passed": 336},
            {**good, "total": 329, "passed": 329},
            {**good, "passed": True, "total": True},
            {**good, "exit_code": 1},
            {**good, "command": "python -m unittest"},
            {**good, "report_sha256": "not-a-sha256"},
        )
        for value in mutations:
            with self.subTest(value=value):
                self.assertFalse(
                    _regression_passed(
                        value,
                        expected_command=PYTHON_REGRESSION_COMMAND,
                        minimum_total=330,
                    )
                )

    def test_node_regression_requires_exact_workdir(self) -> None:
        good = _regression_record(
            command=NODE_REGRESSION_COMMAND,
            total=30,
            workdir=NODE_REGRESSION_WORKDIR,
        )
        self.assertTrue(
            _regression_passed(
                good,
                expected_command=NODE_REGRESSION_COMMAND,
                minimum_total=30,
                expected_workdir=NODE_REGRESSION_WORKDIR,
            )
        )
        self.assertFalse(
            _regression_passed(
                {**good, "workdir": "."},
                expected_command=NODE_REGRESSION_COMMAND,
                minimum_total=30,
                expected_workdir=NODE_REGRESSION_WORKDIR,
            )
        )


class VerifyV09L0TransitionIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repository = Path(self.temporary.name) / "repository"
        self.repository.mkdir()
        self._git("init", "--quiet")
        self._git("config", "user.name", "L0 Transition Test")
        self._git("config", "user.email", "l0-transition@example.invalid")
        self.ledger_path = (
            self.repository
            / "plans"
            / "v0.9-universal-byom"
            / "loop-tasks.json"
        )
        self.ledger_path.parent.mkdir(parents=True)
        self.pre_ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        self.pre_ledger["loops"][0]["status"] = "implemented"
        for task in self.pre_ledger["loops"][0]["tasks"]:
            task["status"] = "implemented"
        self.pre_commit = self._commit_ledger(self.pre_ledger, "pre gate")

    def _git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )

    def _commit_ledger(self, ledger: dict, message: str) -> str:
        self.ledger_path.write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._git("add", "plans/v0.9-universal-byom/loop-tasks.json")
        self._git("commit", "--quiet", "-m", message)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def _verified_source_ledger(self) -> dict:
        ledger = copy.deepcopy(self.pre_ledger)
        ledger["loops"][0]["status"] = "verified"
        for task in ledger["loops"][0]["tasks"]:
            task["status"] = "verified"
        return ledger

    def test_real_git_transition_accepts_only_l0_status_changes(self) -> None:
        source_commit = self._commit_ledger(
            self._verified_source_ledger(),
            "verify L0",
        )
        validate_l0_transition(self.repository, self.pre_commit, source_commit)

    def test_real_git_transition_rejects_later_loop_changes(self) -> None:
        source = self._verified_source_ledger()
        source["loops"][1]["status"] = "verified"
        source_commit = self._commit_ledger(source, "invalid L1 change")
        with self.assertRaisesRegex(AssertionError, "L1-L5 must be identical"):
            validate_l0_transition(self.repository, self.pre_commit, source_commit)

    def test_real_git_transition_rejects_non_status_l0_changes(self) -> None:
        source = self._verified_source_ledger()
        source["loops"][0]["outcome"] = "changed during transition"
        source_commit = self._commit_ledger(source, "invalid L0 contract change")
        with self.assertRaisesRegex(AssertionError, "only its loop and task statuses"):
            validate_l0_transition(self.repository, self.pre_commit, source_commit)

    def test_real_git_transition_requires_machine_verified_source(self) -> None:
        source = self._verified_source_ledger()
        source["loops"][0]["status"] = "accepted"
        source_commit = self._commit_ledger(source, "invalid accepted source")
        with self.assertRaisesRegex(AssertionError, "source L0 must be verified"):
            validate_l0_transition(self.repository, self.pre_commit, source_commit)


if __name__ == "__main__":
    unittest.main()
