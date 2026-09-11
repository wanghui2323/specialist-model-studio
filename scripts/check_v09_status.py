#!/usr/bin/env python3
"""Report whether committed or working-tree changes invalidate v0.9 evidence.

The checker is deliberately read-only.  It never edits the lifecycle ledger or
evidence files; a non-zero exit tells a human that the affected level must be
downgraded and re-verified.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
_FULL_COMMIT = re.compile(r"[0-9a-f]{40}")
_MAX_EVIDENCE_BYTES = 1024 * 1024
_MAX_OWNED_PATHS = 512
_MAX_OWNED_PATH_LENGTH = 1024


class StatusCheckError(RuntimeError):
    """The repository or evidence could not be checked safely."""


@dataclass(frozen=True)
class LevelStatus:
    evidence_path: Path
    source_commit: str
    head_commit: str
    owned_paths: tuple[str, ...]
    changed_paths: tuple[str, ...]

    @property
    def is_current(self) -> bool:
        return not self.changed_paths


def _git_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_LITERAL_PATHSPECS"] = "1"
    environment["LC_ALL"] = "C"
    return environment


def _run_git(
    repository: Path,
    arguments: Sequence[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=check,
            capture_output=True,
            env=_git_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StatusCheckError("git_command_failed") from exc


def validate_repository(repository: str | Path) -> tuple[Path, str]:
    root = Path(repository).expanduser().resolve()
    if not root.is_dir():
        raise StatusCheckError("repository_not_found")
    try:
        top_level = os.fsdecode(
            _run_git(root, ["rev-parse", "--show-toplevel"]).stdout
        ).strip()
        head = os.fsdecode(
            _run_git(root, ["rev-parse", "--verify", "HEAD^{commit}"]).stdout
        ).strip()
    except StatusCheckError as exc:
        raise StatusCheckError("not_a_git_repository") from exc
    if Path(top_level).resolve() != root:
        raise StatusCheckError("repository_root_required")
    if _FULL_COMMIT.fullmatch(head) is None:
        raise StatusCheckError("invalid_head_commit")
    return root, head


def _resolve_evidence_path(repository: Path, evidence_path: str | Path) -> Path:
    candidate = Path(evidence_path).expanduser()
    if not candidate.is_absolute():
        candidate = repository / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(repository)
    except ValueError as exc:
        raise StatusCheckError("evidence_path_outside_repository") from exc
    if not resolved.is_file():
        raise StatusCheckError("evidence_file_missing")
    return resolved


def _read_evidence(path: Path) -> dict[str, object]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise StatusCheckError("evidence_file_unreadable") from exc
    if size < 1 or size > _MAX_EVIDENCE_BYTES:
        raise StatusCheckError("evidence_file_size_invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StatusCheckError("evidence_json_invalid") from exc
    if not isinstance(value, dict):
        raise StatusCheckError("evidence_must_be_object")
    return value


def _validate_evidence_at_head(repository: Path, path: Path) -> str:
    relative = path.relative_to(repository).as_posix()
    tracked = _run_git(
        repository,
        ["ls-files", "--error-unmatch", "--", relative],
        check=False,
    )
    if tracked.returncode != 0:
        raise StatusCheckError("evidence_file_untracked")
    for arguments in (
        ["diff", "--quiet", "--no-ext-diff", "--", relative],
        ["diff", "--cached", "--quiet", "--no-ext-diff", "--", relative],
    ):
        result = _run_git(repository, arguments, check=False)
        if result.returncode == 1:
            raise StatusCheckError("evidence_file_dirty")
        if result.returncode != 0:
            raise StatusCheckError("evidence_file_state_check_failed")
    blob = _run_git(
        repository,
        ["cat-file", "-e", f"HEAD:{relative}"],
        check=False,
    )
    if blob.returncode != 0:
        raise StatusCheckError("evidence_file_missing_from_head")
    return relative


def _validate_owned_path(repository: Path, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_OWNED_PATH_LENGTH
        or "\\" in value
        or "\x00" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or value.startswith(":")
        or re.match(r"^[A-Za-z]:", value) is not None
    ):
        raise StatusCheckError("owned_path_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
        raise StatusCheckError("owned_path_outside_repository")
    if value != "." and (not path.parts or path.as_posix() != value):
        raise StatusCheckError("owned_path_not_normalized")
    resolved = (repository / path.as_posix()).resolve()
    try:
        resolved.relative_to(repository)
    except ValueError as exc:
        raise StatusCheckError("owned_path_outside_repository") from exc
    return value


def _validated_fields(
    repository: Path,
    evidence: dict[str, object],
) -> tuple[str, tuple[str, ...]]:
    source_commit = evidence.get("source_commit")
    if not isinstance(source_commit, str):
        raise StatusCheckError("source_commit_missing")
    if _FULL_COMMIT.fullmatch(source_commit) is None:
        raise StatusCheckError("source_commit_invalid")
    owned_values = evidence.get("owned_paths")
    if not isinstance(owned_values, list) or not owned_values:
        raise StatusCheckError("owned_paths_missing")
    if len(owned_values) > _MAX_OWNED_PATHS:
        raise StatusCheckError("owned_paths_limit_exceeded")
    owned_paths = tuple(
        _validate_owned_path(repository, value) for value in owned_values
    )
    if len(set(owned_paths)) != len(owned_paths):
        raise StatusCheckError("owned_paths_duplicate")
    return source_commit, owned_paths


def _validate_source_commit(
    repository: Path,
    source_commit: str,
    head_commit: str,
) -> None:
    try:
        _run_git(repository, ["cat-file", "-e", f"{source_commit}^{{commit}}"])
    except StatusCheckError as exc:
        raise StatusCheckError("source_commit_not_found") from exc
    ancestor = _run_git(
        repository,
        ["merge-base", "--is-ancestor", source_commit, head_commit],
        check=False,
    )
    if ancestor.returncode == 1:
        raise StatusCheckError("source_commit_not_ancestor_of_head")
    if ancestor.returncode != 0:
        raise StatusCheckError("source_commit_ancestry_check_failed")


def _validate_owned_paths_at_source(
    repository: Path,
    source_commit: str,
    owned_paths: tuple[str, ...],
) -> None:
    for owned_path in owned_paths:
        if owned_path == ".":
            continue
        exists = _run_git(
            repository,
            ["cat-file", "-e", f"{source_commit}:{owned_path}"],
            check=False,
        )
        if exists.returncode != 0:
            raise StatusCheckError("owned_path_not_in_source_commit")


def _decoded_paths(output: bytes) -> tuple[str, ...]:
    return tuple(os.fsdecode(value) for value in output.split(b"\0") if value)


def _changed_owned_paths(
    repository: Path,
    source_commit: str,
    head_commit: str,
    owned_paths: tuple[str, ...],
) -> tuple[str, ...]:
    commands = (
        (
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            f"{source_commit}..{head_commit}",
            "--",
            *owned_paths,
        ),
        (
            "diff",
            "--cached",
            "--name-only",
            "-z",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            "--",
            *owned_paths,
        ),
        (
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            "--",
            *owned_paths,
        ),
        (
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            *owned_paths,
        ),
    )
    changed: dict[str, None] = {}
    for command in commands:
        for path in _decoded_paths(_run_git(repository, command).stdout):
            changed[path] = None
    return tuple(changed)


def check_level_evidence(
    repository: str | Path,
    evidence_path: str | Path,
    *,
    validated_head: str | None = None,
) -> LevelStatus:
    root, observed_head = validate_repository(repository)
    if validated_head is not None and validated_head != observed_head:
        raise StatusCheckError("head_changed_during_status_check")
    path = _resolve_evidence_path(root, evidence_path)
    _validate_evidence_at_head(root, path)
    evidence = _read_evidence(path)
    source_commit, owned_paths = _validated_fields(root, evidence)
    _validate_source_commit(root, source_commit, observed_head)
    _validate_owned_paths_at_source(root, source_commit, owned_paths)
    changed_paths = _changed_owned_paths(
        root,
        source_commit,
        observed_head,
        owned_paths,
    )
    final_head = os.fsdecode(
        _run_git(root, ["rev-parse", "--verify", "HEAD^{commit}"]).stdout
    ).strip()
    if final_head != observed_head:
        raise StatusCheckError("head_changed_during_status_check")
    _validate_evidence_at_head(root, path)
    return LevelStatus(
        evidence_path=path,
        source_commit=source_commit,
        head_commit=observed_head,
        owned_paths=owned_paths,
        changed_paths=changed_paths,
    )


def discover_level_evidence(repository: str | Path) -> tuple[Path, ...]:
    root, _head = validate_repository(repository)
    evidence_dir = root / "plans" / "v0.9-universal-byom"
    paths = tuple(
        evidence_dir / f"l{level}-evidence.json"
        for level in range(6)
        if (evidence_dir / f"l{level}-evidence.json").is_file()
    )
    if not paths:
        raise StatusCheckError("no_level_evidence_found")
    return paths


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail when committed or working-tree changes invalidate v0.9 evidence."
    )
    parser.add_argument(
        "evidence",
        nargs="*",
        help="Evidence JSON paths relative to the repository (default: existing L0-L5 files).",
    )
    parser.add_argument(
        "--repo-root",
        default=str(ROOT),
        help="Exact Git repository root.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        repository, head = validate_repository(arguments.repo_root)
        evidence_paths: Sequence[str | Path]
        if arguments.evidence:
            evidence_paths = arguments.evidence
        else:
            evidence_paths = discover_level_evidence(repository)
    except StatusCheckError as exc:
        print(f"[INVALID] {exc}", file=sys.stderr)
        return 2

    invalid = False
    stale = False
    for evidence_path in evidence_paths:
        try:
            status = check_level_evidence(
                repository,
                evidence_path,
                validated_head=head,
            )
        except StatusCheckError as exc:
            invalid = True
            print(f"[INVALID] {evidence_path}: {exc}", file=sys.stderr)
            continue
        relative_evidence = status.evidence_path.relative_to(repository).as_posix()
        if status.is_current:
            print(
                f"[CURRENT] {relative_evidence}: "
                f"{status.source_commit}..{status.head_commit} has no owned-path changes"
            )
        else:
            stale = True
            print(
                f"[STALE] {relative_evidence}: changed owned paths: "
                + ", ".join(status.changed_paths),
                file=sys.stderr,
            )
    if invalid:
        return 2
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
