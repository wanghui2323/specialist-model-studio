from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.verify_v10_rc import (
    VerificationError,
    build_blocked_template,
    capture_source_state,
    derive_summary,
    load_gate_contract,
    main,
    validate_report,
)


ROOT = Path(__file__).resolve().parents[1]


class VerifyV10RcTests(unittest.TestCase):
    def _git(self, root: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.strip()

    def _clean_source(self, parent: Path) -> tuple[Path, str]:
        source = parent / "source"
        source.mkdir()
        self._git(source, "init", "--quiet")
        self._git(source, "config", "user.name", "RC Test")
        self._git(source, "config", "user.email", "rc-test@example.invalid")
        (source / "tracked.txt").write_text("candidate\n", encoding="utf-8")
        self._git(source, "add", "tracked.txt")
        self._git(source, "commit", "--quiet", "-m", "candidate")
        return source, self._git(source, "rev-parse", "HEAD")

    def _report_and_evidence(
        self, parent: Path, source: Path
    ) -> tuple[dict, Path, dict]:
        contract = load_gate_contract(ROOT / "acceptance" / "v1.0-gates.json")
        source_state = capture_source_state(source)
        report = build_blocked_template(contract, source_state)
        report_root = parent / "report"
        evidence_root = report_root / "evidence"
        evidence_root.mkdir(parents=True)
        evidence_path = evidence_root / "gate-evidence.json"
        evidence_path.write_text('{"verified":true}\n', encoding="utf-8")
        evidence = {
            "path": "evidence/gate-evidence.json",
            "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            "description": "Synthetic immutable gate evidence",
        }
        return report, report_root / "acceptance-report.json", evidence

    def _pass_levels(
        self, report: dict, evidence: dict, levels: set[str]
    ) -> None:
        for gate in report["gates"]:
            if gate["level_id"] in levels:
                gate["status"] = "passed"
                gate["summary"] = "Verified by immutable evidence."
                gate["evidence_refs"] = [dict(evidence)]
                gate["blockers"] = []
        report["summary"] = derive_summary(
            report["gates"], source_dirty=report["source"]["source_dirty"]
        )

    def test_cli_generates_and_validates_an_all_blocked_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source, commit = self._clean_source(parent)
            report_path = parent / "evidence" / "acceptance-report.json"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(
                    [
                        "template",
                        "--output",
                        str(report_path),
                        "--source-root",
                        str(source),
                        "--expected-source-commit",
                        commit,
                    ]
                )
            self.assertEqual(result, 0, output.getvalue())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(len(report["gates"]), 8)
            self.assertEqual(
                {gate["status"] for gate in report["gates"]}, {"blocked"}
            )
            self.assertEqual(report["summary"]["public_rc_status"], "blocked")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(
                    [
                        "validate",
                        "--report",
                        str(report_path),
                        "--source-root",
                        str(source),
                        "--expected-source-commit",
                        commit,
                    ]
                )
            self.assertEqual(result, 0, output.getvalue())

            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                result = main(
                    [
                        "validate",
                        "--report",
                        str(report_path),
                        "--source-root",
                        str(source),
                        "--expected-source-commit",
                        commit,
                        "--require-public-rc",
                    ]
                )
            self.assertEqual(result, 1)
            self.assertIn("public_rc_status must equal 'passed'", error.getvalue())

    def test_public_and_github_release_aggregate_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source, commit = self._clean_source(parent)
            report, report_path, evidence = self._report_and_evidence(parent, source)
            contract = load_gate_contract()
            source_state = capture_source_state(source)

            self._pass_levels(
                report,
                evidence,
                {"L0", "L1", "L2", "L3", "L4", "L5", "L6"},
            )
            summary = validate_report(
                report,
                report_path=report_path,
                contract=contract,
                source_state=source_state,
                expected_source_commit=commit,
            )
            self.assertEqual(summary["local_review_status"], "passed")
            self.assertEqual(summary["public_rc_status"], "passed")
            self.assertEqual(summary["github_release_status"], "blocked")

            self._pass_levels(report, evidence, {"release"})
            summary = validate_report(
                report,
                report_path=report_path,
                contract=contract,
                source_state=source_state,
                expected_source_commit=commit,
            )
            self.assertEqual(summary["github_release_status"], "passed")

    def test_exact_commit_and_actual_dirty_state_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source, commit = self._clean_source(parent)
            report, report_path, _evidence = self._report_and_evidence(parent, source)
            contract = load_gate_contract()
            clean_state = capture_source_state(source)

            with self.assertRaisesRegex(VerificationError, "source_commit"):
                validate_report(
                    report,
                    report_path=report_path,
                    contract=contract,
                    source_state=clean_state,
                    expected_source_commit="f" * 40,
                )

            (source / "untracked.txt").write_text("dirty\n", encoding="utf-8")
            dirty_state = capture_source_state(source)
            self.assertTrue(dirty_state["source_dirty"])
            with self.assertRaisesRegex(VerificationError, "source_dirty"):
                validate_report(
                    report,
                    report_path=report_path,
                    contract=contract,
                    source_state=dirty_state,
                    expected_source_commit=commit,
                )

    def test_passed_gate_requires_existing_digest_bound_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source, commit = self._clean_source(parent)
            report, report_path, evidence = self._report_and_evidence(parent, source)
            contract = load_gate_contract()
            source_state = capture_source_state(source)
            self._pass_levels(report, evidence, {"L0"})

            report["gates"][0]["evidence_refs"][0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(VerificationError, "sha256 mismatch"):
                validate_report(
                    report,
                    report_path=report_path,
                    contract=contract,
                    source_state=source_state,
                    expected_source_commit=commit,
                )

            report["gates"][0]["evidence_refs"] = []
            with self.assertRaisesRegex(VerificationError, "must reference"):
                validate_report(
                    report,
                    report_path=report_path,
                    contract=contract,
                    source_state=source_state,
                    expected_source_commit=commit,
                )

            report["gates"][0]["evidence_refs"] = [
                {"path": "../outside.json", "sha256": "0" * 64}
            ]
            with self.assertRaisesRegex(VerificationError, "stay below"):
                validate_report(
                    report,
                    report_path=report_path,
                    contract=contract,
                    source_state=source_state,
                    expected_source_commit=commit,
                )

    def test_gate_identity_status_and_summary_cannot_be_forged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source, commit = self._clean_source(parent)
            report, report_path, _evidence = self._report_and_evidence(parent, source)
            contract = load_gate_contract()
            source_state = capture_source_state(source)

            report["gates"][0]["status"] = "skipped"
            with self.assertRaisesRegex(VerificationError, "status"):
                validate_report(
                    report,
                    report_path=report_path,
                    contract=contract,
                    source_state=source_state,
                    expected_source_commit=commit,
                )

            report = build_blocked_template(contract, source_state)
            report["summary"]["public_rc_status"] = "passed"
            with self.assertRaisesRegex(VerificationError, "summary must be derived"):
                validate_report(
                    report,
                    report_path=report_path,
                    contract=contract,
                    source_state=source_state,
                    expected_source_commit=commit,
                )


if __name__ == "__main__":
    unittest.main()
