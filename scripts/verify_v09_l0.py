#!/usr/bin/env python3
"""Fail-closed structural gate for the v0.9 Universal BYOM L0 contract."""

from __future__ import annotations

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


def _require(text: str, *needles: str) -> None:
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise AssertionError(f"missing required contract terms: {missing}")


def main() -> None:
    required = {
        "requirements": PLAN / "requirements.md",
        "objects": PLAN / "object-model.md",
        "closure": PLAN / "closure-matrix.md",
        "acceptance": PLAN / "acceptance-contract.md",
        "ledger": PLAN / "loop-tasks.json",
        "baseline": PLAN / "baseline-evidence.json",
        "l0_evidence": PLAN / "l0-evidence.json",
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
    if len(ledger.get("confirmed_decisions", [])) < 4:
        raise AssertionError("confirmed product decisions are incomplete")

    if baseline.get("iteration") != "v0.9-universal-byom":
        raise AssertionError("baseline iteration mismatch")
    baseline_commit = str(baseline.get("source", {}).get("baseline_commit", ""))
    if not re.fullmatch(r"[0-9a-f]{7,40}", baseline_commit):
        raise AssertionError("baseline commit is not a Git commit")
    subprocess.run(
        ["git", "cat-file", "-e", f"{baseline_commit}^{{commit}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    decisions = baseline.get("confirmed_decisions", [])
    if len(decisions) != 4:
        raise AssertionError("baseline must record exactly four confirmed decisions")
    if baseline.get("truth_boundary", "").find("not evidence") < 0:
        raise AssertionError("baseline truth boundary is missing")

    if l0_evidence.get("gate") != "V09-L0-CONTRACT-BASELINE":
        raise AssertionError("L0 evidence gate mismatch")
    if l0_evidence.get("result") != "passed":
        raise AssertionError("L0 evidence does not record a passed gate")
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
        "390×844",
        "1440×900",
        "6/6",
    )
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
        "baseline_commit": baseline_commit,
        "loops": len(loops),
        "tasks": sum(len(item.get("tasks", [])) for item in loops),
        "closure_rows": len(closure_ids),
        "confirmed_decisions": len(decisions),
        "required_files": len(required),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
