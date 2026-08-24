#!/usr/bin/env python3
"""Fail-closed structural gate for the v0.9 Universal BYOM L0 contract."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

try:
    from scripts.check_v09_status import StatusCheckError, check_level_evidence
except ModuleNotFoundError:  # Direct execution: python scripts/verify_v09_l0.py
    from check_v09_status import StatusCheckError, check_level_evidence


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "plans" / "v0.9-universal-byom"
ALLOWED_LIFECYCLE_STATES = {
    "planned",
    "implementing",
    "implemented",
    "verified",
    "accepted",
}
EXPECTED_LOOP_IDS = ["L0", "L1", "L2", "L3", "L4", "L5"]
STATIC_L0_PATHS = (
    "AGENTS.md",
    "plans/v0.9-universal-byom/requirements.md",
    "plans/v0.9-universal-byom/object-model.md",
    "plans/v0.9-universal-byom/closure-matrix.md",
    "plans/v0.9-universal-byom/acceptance-contract.md",
    "plans/v0.9-universal-byom/baseline-evidence.json",
    "scripts/check_v09_status.py",
    "scripts/verify_v09_l0.py",
)
PYTHON_REGRESSION_COMMAND = ".venv/bin/python -m unittest discover -s tests"
NODE_REGRESSION_COMMAND = "npm run check && npm test"
NODE_REGRESSION_WORKDIR = "integrations/deepseek-harness"
_FULL_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _read(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object: {path.relative_to(ROOT)}")
    return value


def _git_blob(commit: str, path: str, *, repository: Path = ROOT) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=repository,
        check=True,
        capture_output=True,
    ).stdout


def _require(text: str, *needles: str) -> None:
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise AssertionError(f"missing required contract terms: {missing}")


def validate_ledger_for_l0_gate(
    ledger: dict,
    *,
    require_passed: bool = True,
) -> list[dict]:
    loops = ledger.get("loops")
    if not isinstance(loops, list) or [item.get("loop_id") for item in loops] != EXPECTED_LOOP_IDS:
        raise AssertionError("ledger must contain ordered L0-L5 loops")
    planning_states = [item.get("status") for item in loops]
    planning_states.extend(
        task.get("status") for item in loops for task in item.get("tasks", [])
    )
    unsupported = set(planning_states) - ALLOWED_LIFECYCLE_STATES
    if unsupported:
        raise AssertionError(
            f"transition ledger contains unsupported lifecycle states: {sorted(unsupported)}"
        )
    if not require_passed:
        return loops
    if loops[0].get("status") not in {"verified", "accepted"}:
        raise AssertionError("L0 gate requires verified or accepted L0")
    l0_tasks = loops[0].get("tasks", [])
    if not isinstance(l0_tasks, list) or [task.get("id") for task in l0_tasks] != [
        "MH-900",
        "MH-901",
        "MH-902",
    ]:
        raise AssertionError("L0 task inventory must be ordered MH-900 through MH-902")
    task_states = {str(task.get("id")): task.get("status") for task in l0_tasks}
    if task_states != {
        "MH-900": "verified",
        "MH-901": "verified",
        "MH-902": "verified",
    }:
        raise AssertionError("L0 tasks MH-900 through MH-902 must be verified")
    return loops


def _regression_passed(
    value: object,
    *,
    expected_command: str,
    minimum_total: int,
    expected_workdir: str | None = None,
) -> bool:
    return (
        isinstance(value, dict)
        and value.get("command") == expected_command
        and (expected_workdir is None or value.get("workdir") == expected_workdir)
        and type(value.get("exit_code")) is int
        and value["exit_code"] == 0
        and type(value.get("passed")) is int
        and type(value.get("total")) is int
        and value["total"] >= minimum_total
        and value["passed"] == value["total"]
        and isinstance(value.get("report_sha256"), str)
        and _SHA256.fullmatch(value["report_sha256"]) is not None
    )


def _ordered_loops(ledger: dict) -> list[dict]:
    return validate_ledger_for_l0_gate(ledger, require_passed=False)


def _l0_task_states(loop: dict) -> tuple[list[str], list[object]]:
    tasks = loop.get("tasks", [])
    if not isinstance(tasks, list):
        raise AssertionError("L0 tasks must be a list")
    return (
        [str(task.get("id")) for task in tasks],
        [task.get("status") for task in tasks],
    )


def validate_l0_transition(
    repository: Path,
    pre_gate_commit: str,
    source_commit: str,
) -> None:
    if _FULL_COMMIT.fullmatch(pre_gate_commit) is None:
        raise AssertionError("pre_gate_commit must be a full 40-character commit")
    if _FULL_COMMIT.fullmatch(source_commit) is None:
        raise AssertionError("source_commit must be a full 40-character commit")
    if pre_gate_commit == source_commit:
        raise AssertionError("pre_gate_commit must differ from source_commit")
    subprocess.run(
        ["git", "cat-file", "-e", f"{pre_gate_commit}^{{commit}}"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "cat-file", "-e", f"{source_commit}^{{commit}}"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", pre_gate_commit, source_commit],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    pre_ledger = json.loads(
        _git_blob(
            pre_gate_commit,
            "plans/v0.9-universal-byom/loop-tasks.json",
            repository=repository,
        )
    )
    source_ledger = json.loads(
        _git_blob(
            source_commit,
            "plans/v0.9-universal-byom/loop-tasks.json",
            repository=repository,
        )
    )
    pre_loops = _ordered_loops(pre_ledger)
    source_loops = _ordered_loops(source_ledger)
    if pre_loops[0].get("status") != "implemented":
        raise AssertionError("pre-gate L0 must be implemented")
    if source_loops[0].get("status") != "verified":
        raise AssertionError("source L0 must be verified")
    expected_ids = ["MH-900", "MH-901", "MH-902"]
    pre_ids, pre_states = _l0_task_states(pre_loops[0])
    source_ids, source_states = _l0_task_states(source_loops[0])
    if pre_ids != expected_ids or pre_states != ["implemented"] * 3:
        raise AssertionError("pre-gate MH-900 through MH-902 must be implemented")
    if source_ids != expected_ids or source_states != ["verified"] * 3:
        raise AssertionError("source MH-900 through MH-902 must be verified")
    if pre_loops[1:] != source_loops[1:]:
        raise AssertionError("L1-L5 must be identical across the L0 transition")
    normalized_pre_l0 = json.loads(json.dumps(pre_loops[0]))
    normalized_source_l0 = json.loads(json.dumps(source_loops[0]))
    normalized_pre_l0["status"] = normalized_source_l0["status"] = "<l0-status>"
    for task in normalized_pre_l0["tasks"]:
        task["status"] = "<l0-task-status>"
    for task in normalized_source_l0["tasks"]:
        task["status"] = "<l0-task-status>"
    if normalized_pre_l0 != normalized_source_l0:
        raise AssertionError("L0 may change only its loop and task statuses")


def main() -> None:
    required = {
        "agents": ROOT / "AGENTS.md",
        "requirements": PLAN / "requirements.md",
        "objects": PLAN / "object-model.md",
        "closure": PLAN / "closure-matrix.md",
        "acceptance": PLAN / "acceptance-contract.md",
        "ledger": PLAN / "loop-tasks.json",
        "baseline": PLAN / "baseline-evidence.json",
        "l0_evidence": PLAN / "l0-evidence.json",
        "iteration_plan": PLAN / "ITERATION-PLAN.md",
        "workbench": PLAN / "index.html",
        "styles": PLAN / "styles.css",
        "javascript": PLAN / "workbench.js",
    }
    texts = {name: _read(path) for name, path in required.items() if path.suffix != ".json"}
    ledger = _json(required["ledger"])
    baseline = _json(required["baseline"])
    l0_evidence = _json(required["l0_evidence"])

    try:
        evidence_status = check_level_evidence(ROOT, required["l0_evidence"])
    except StatusCheckError as exc:
        raise AssertionError(f"L0 evidence status invalid: {exc}") from exc
    if not evidence_status.is_current:
        raise AssertionError(
            "L0 evidence owned paths changed: " + ", ".join(evidence_status.changed_paths)
        )

    if ledger.get("iteration") != "v0.9 Universal BYOM":
        raise AssertionError("unexpected iteration ledger")
    loops = validate_ledger_for_l0_gate(ledger)

    if baseline.get("iteration") != "v0.9-universal-byom":
        raise AssertionError("baseline iteration mismatch")
    baseline_commit = str(baseline.get("source", {}).get("baseline_commit", ""))
    if not re.fullmatch(r"[0-9a-f]{7,40}", baseline_commit):
        raise AssertionError("baseline commit is not a Git commit")
    resolved_baseline_commit = subprocess.run(
        ["git", "rev-parse", baseline_commit],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    decisions = baseline.get("confirmed_decisions", [])
    if len(decisions) != 4:
        raise AssertionError("baseline must record exactly four confirmed decisions")
    if baseline.get("truth_boundary", "").find("not evidence") < 0:
        raise AssertionError("baseline truth boundary is missing")

    if l0_evidence.get("gate") != "V09-L0-CONTRACT-BASELINE":
        raise AssertionError("L0 evidence gate mismatch")
    if l0_evidence.get("result") != "passed":
        raise AssertionError("L0 evidence does not record a passed gate")
    if l0_evidence.get("baseline_commit") != resolved_baseline_commit:
        raise AssertionError("L0 evidence does not bind the full baseline commit")
    pre_gate_commit = str(l0_evidence.get("pre_gate_commit", ""))
    source_commit = str(l0_evidence.get("source_commit", ""))
    if _FULL_COMMIT.fullmatch(source_commit) is None:
        raise AssertionError("L0 evidence source_commit must be a full 40-character commit")
    subprocess.run(
        ["git", "cat-file", "-e", f"{source_commit}^{{commit}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if l0_evidence.get("producer_commit") != source_commit:
        raise AssertionError("L0 evidence producer_commit must equal source_commit")
    validate_l0_transition(ROOT, pre_gate_commit, source_commit)
    source_ledger = json.loads(
        _git_blob(source_commit, "plans/v0.9-universal-byom/loop-tasks.json")
    )
    source_decisions = source_ledger.get("confirmed_decisions", [])
    if not isinstance(source_decisions, list) or len(source_decisions) != 9:
        raise AssertionError("source confirmed product decisions are incomplete")
    expected_transition = {
        "pre_gate_commit": pre_gate_commit,
        "pre_gate": "implemented",
        "gate_result": "passed",
        "post_gate": "verified",
        "authority": "ITERATION-PLAN.md#V0",
        "scope": "L0 loop and tasks MH-900 through MH-902",
    }
    if l0_evidence.get("status_transition") != expected_transition:
        raise AssertionError("L0 status transition evidence mismatch")
    if l0_evidence.get("structural_gate", {}).get("confirmed_decisions") != len(
        source_decisions
    ):
        raise AssertionError("source confirmed decision count mismatch")
    browser = l0_evidence.get("browser", {})
    if browser.get("desktop", {}).get("viewport") != "1440x900":
        raise AssertionError("desktop browser evidence is missing")
    if browser.get("mobile", {}).get("viewport") != "390x844":
        raise AssertionError("mobile browser evidence is missing")
    for viewport in ("desktop", "mobile"):
        result = browser.get(viewport, {})
        if result.get("horizontal_overflow") is not False:
            raise AssertionError(f"{viewport} browser evidence contains horizontal overflow")
        if result.get("tiny_visible_targets") != 0:
            raise AssertionError(f"{viewport} browser evidence contains tiny visible targets")
    if not _regression_passed(
        l0_evidence.get("regression", {}).get("python"),
        expected_command=PYTHON_REGRESSION_COMMAND,
        minimum_total=330,
    ):
        raise AssertionError("Python regression evidence mismatch")
    if not _regression_passed(
        l0_evidence.get("regression", {}).get("node"),
        expected_command=NODE_REGRESSION_COMMAND,
        minimum_total=30,
        expected_workdir=NODE_REGRESSION_WORKDIR,
    ):
        raise AssertionError("Node regression evidence mismatch")

    artifact_paths = {path: ROOT / path for path in STATIC_L0_PATHS}
    recorded_hashes = l0_evidence.get("artifact_sha256", {})
    if set(recorded_hashes) != set(artifact_paths):
        raise AssertionError("L0 evidence artifact hash inventory mismatch")
    for name, path in artifact_paths.items():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if recorded_hashes.get(name) != actual:
            raise AssertionError(f"L0 evidence artifact hash mismatch: {name}")

    owned_paths = l0_evidence.get("owned_paths")
    if owned_paths != list(STATIC_L0_PATHS):
        raise AssertionError("L0 evidence owned_paths inventory mismatch")
    for repo_path in STATIC_L0_PATHS:
        source_hash = hashlib.sha256(_git_blob(source_commit, repo_path)).hexdigest()
        if source_hash != recorded_hashes[repo_path]:
            raise AssertionError(f"source commit blob mismatch: {repo_path}")

    combined = "\n".join(texts.values())
    _require(
        combined,
        "TrainingTask",
        "Hugging Face",
        "GitHub",
        "SourceSnapshot",
        "RepositoryAnalysis",
        "TrainingPlanRevision",
        "EnvironmentLock",
        "ResourceFitReport",
        "BuildAttempt",
        "QualificationRun",
        "RecipeVersion",
        "BlockerEvidence",
        "OCI",
        "patch_origin",
        "accelerator_policy",
        "CPU-only inside the isolation boundary",
        "390×844",
        "1440×900",
        "6/6",
    )
    _require(
        texts["acceptance"],
        "planned / implementing / implemented",
        "`verified` 只由绑定冻结 commit 的机器证据产生",
    )
    if sum(texts["objects"].count(term) for term in ("patch_origin", "accelerator_policy")) < 4:
        raise AssertionError("V0 object-model patch and accelerator policy gate failed")
    forbidden_terms = {
        "agents": ["Do not imply arbitrary Hub model fine-tuning"],
        "requirements": ["Agent 只能提出新 attempt", "自动修复"],
        "closure": ["Agent 修复 Loop", "真实自动修复缺失"],
    }
    for document, terms in forbidden_terms.items():
        present = [term for term in terms if term in texts[document]]
        if present:
            raise AssertionError(f"obsolete contract terms remain in {document}: {present}")
    closure_ids = re.findall(r"^\| (C\d{2}) \|", texts["closure"], re.MULTILINE)
    if closure_ids != [f"C{index:02d}" for index in range(1, 16)]:
        raise AssertionError("closure matrix must contain ordered C01-C15")
    for row in re.findall(r"^\| C\d{2} \|.*$", texts["closure"], re.MULTILINE):
        if row.count("|") < 10:
            raise AssertionError(f"incomplete closure row: {row[:80]}")

    html_ids = set(re.findall(r'id="([A-Za-z][A-Za-z0-9_-]*)"', texts["workbench"]))
    js_ids_match = re.search(
        r"const ui = Object\.fromEntries\(\[(.*?)\]\.map",
        texts["javascript"],
        re.DOTALL,
    )
    if not js_ids_match:
        raise AssertionError("workbench UI binding list not found")
    js_ids = set(re.findall(r'"([A-Za-z][A-Za-z0-9_-]*)"', js_ids_match.group(1)))
    if js_ids - html_ids:
        raise AssertionError(f"workbench references missing HTML IDs: {sorted(js_ids - html_ids)}")
    if "v0.9 已实现" in texts["workbench"] or "v0.9 已验证" in texts["workbench"]:
        raise AssertionError("workbench contains a false completion claim")

    summary = {
        "gate": "V09-L0-CONTRACT-BASELINE",
        "result": "passed",
        "baseline_commit": resolved_baseline_commit,
        "source_commit": source_commit,
        "loops": len(loops),
        "tasks": sum(len(item.get("tasks", [])) for item in loops),
        "closure_rows": len(closure_ids),
        "baseline_confirmed_decisions": len(decisions),
        "confirmed_decisions": len(source_decisions),
        "required_files": len(required),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
