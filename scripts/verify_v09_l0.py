#!/usr/bin/env python3
"""Fail-closed structural gate for the v0.9 Universal BYOM L0 contract."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "plans" / "v0.9-universal-byom"


def _read(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object: {path.relative_to(ROOT)}")
    return value


def _git_blob(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _require(text: str, *needles: str) -> None:
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise AssertionError(f"missing required contract terms: {missing}")


def main() -> None:
    tracked_status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if tracked_status:
        raise AssertionError("L0 gate requires a clean tracked worktree")

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

    if ledger.get("iteration") != "v0.9 Universal BYOM":
        raise AssertionError("unexpected iteration ledger")
    loops = ledger.get("loops")
    if not isinstance(loops, list) or [item.get("loop_id") for item in loops] != [
        "L0",
        "L1",
        "L2",
        "L3",
        "L4",
        "L5",
    ]:
        raise AssertionError("ledger must contain ordered L0-L5 loops")
    allowed_planning_states = {"planned", "implementing", "verified"}
    planning_states = [item.get("status") for item in loops]
    planning_states.extend(
        task.get("status") for item in loops for task in item.get("tasks", [])
    )
    if set(planning_states) - allowed_planning_states:
        raise AssertionError("L0 transition ledger contains an unsupported lifecycle state")
    if loops[0].get("status") != "verified" or any(
        task.get("status") != "verified" for task in loops[0].get("tasks", [])
    ):
        raise AssertionError("L0 and its tasks must be verified after the machine gate")
    if loops[1].get("status") != "implementing":
        raise AssertionError("L1 must be implementing after the L0 transition")
    l1_task_states = [task.get("status") for task in loops[1].get("tasks", [])]
    if l1_task_states != ["implementing", "planned", "planned"]:
        raise AssertionError("expected only the first dependency-safe L1 task to be implementing")
    if any(item.get("status") != "planned" for item in loops[2:]):
        raise AssertionError("L2-L5 must remain planned at the L0 exit gate")
    if any(
        task.get("status") != "planned"
        for item in loops[2:]
        for task in item.get("tasks", [])
    ):
        raise AssertionError("L2-L5 tasks must remain planned at the L0 exit gate")
    current_decisions = ledger.get("confirmed_decisions", [])
    if len(current_decisions) != 9:
        raise AssertionError("confirmed product decisions are incomplete")

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
    source_commit = str(l0_evidence.get("source_commit", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
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
    expected_transition = {
        "pre_gate": "implementing",
        "gate_result": "passed",
        "post_gate": "verified",
        "authority": "ITERATION-PLAN.md#V0",
    }
    if l0_evidence.get("status_transition") != expected_transition:
        raise AssertionError("L0 status transition evidence mismatch")
    if l0_evidence.get("structural_gate", {}).get("confirmed_decisions") != len(
        current_decisions
    ):
        raise AssertionError("current confirmed decision count mismatch")
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
    if l0_evidence.get("regression", {}).get("python") != {"passed": 163, "total": 163}:
        raise AssertionError("Python regression evidence mismatch")
    if l0_evidence.get("regression", {}).get("node") != {"passed": 20, "total": 20}:
        raise AssertionError("Node regression evidence mismatch")

    artifact_paths = {
        "AGENTS.md": required["agents"],
        "requirements.md": required["requirements"],
        "object-model.md": required["objects"],
        "closure-matrix.md": required["closure"],
        "acceptance-contract.md": required["acceptance"],
        "baseline-evidence.json": required["baseline"],
        "ITERATION-PLAN.md": required["iteration_plan"],
        "index.html": required["workbench"],
        "styles.css": required["styles"],
        "workbench.js": required["javascript"],
        "loop-tasks.json": required["ledger"],
        "scripts/verify_v09_l0.py": ROOT / "scripts" / "verify_v09_l0.py",
    }
    recorded_hashes = l0_evidence.get("artifact_sha256", {})
    if set(recorded_hashes) != set(artifact_paths):
        raise AssertionError("L0 evidence artifact hash inventory mismatch")
    for name, path in artifact_paths.items():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if recorded_hashes.get(name) != actual:
            raise AssertionError(f"L0 evidence artifact hash mismatch: {name}")

    stable_source_paths = {
        "AGENTS.md": "AGENTS.md",
        "requirements.md": "plans/v0.9-universal-byom/requirements.md",
        "object-model.md": "plans/v0.9-universal-byom/object-model.md",
        "closure-matrix.md": "plans/v0.9-universal-byom/closure-matrix.md",
        "acceptance-contract.md": "plans/v0.9-universal-byom/acceptance-contract.md",
        "baseline-evidence.json": "plans/v0.9-universal-byom/baseline-evidence.json",
        "ITERATION-PLAN.md": "plans/v0.9-universal-byom/ITERATION-PLAN.md",
        "index.html": "plans/v0.9-universal-byom/index.html",
        "styles.css": "plans/v0.9-universal-byom/styles.css",
        "workbench.js": "plans/v0.9-universal-byom/workbench.js",
        "scripts/verify_v09_l0.py": "scripts/verify_v09_l0.py",
    }
    for name, repo_path in stable_source_paths.items():
        source_hash = hashlib.sha256(_git_blob(source_commit, repo_path)).hexdigest()
        if source_hash != recorded_hashes[name]:
            raise AssertionError(f"source commit blob mismatch: {name}")

    source_ledger = json.loads(
        _git_blob(source_commit, "plans/v0.9-universal-byom/loop-tasks.json")
    )
    source_loops = source_ledger.get("loops", [])
    if not source_loops or source_loops[0].get("status") != "implementing":
        raise AssertionError("source commit must preserve the pre-gate L0 state")
    if any(task.get("status") != "implementing" for task in source_loops[0].get("tasks", [])):
        raise AssertionError("source commit L0 tasks must all be implementing")
    source_loops[0]["status"] = "verified"
    for task in source_loops[0].get("tasks", []):
        task["status"] = "verified"
    if source_ledger != ledger:
        raise AssertionError("loop ledger changed beyond the authorized L0 status transition")

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
        "本轮 L0 合同创建不得预填这些状态",
        "所有 L0–L5 状态仍为 `planned / implementing`",
    )
    _require(texts["iteration_plan"], "V0 全部完成后再改回")
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
        "confirmed_decisions": len(current_decisions),
        "required_files": len(required),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
