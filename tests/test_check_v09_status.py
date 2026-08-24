from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from scripts.check_v09_status import (
    StatusCheckError,
    check_level_evidence,
    main,
    validate_repository,
)


class CheckV09StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repository = Path(self.temporary.name) / "repository"
        self.repository.mkdir()
        self._git("init", "--quiet")
        self._git("config", "user.name", "Status Checker")
        self._git("config", "user.email", "status@example.invalid")
        self._write("src/model.py", "VERSION = 1\n")
        self._write("docs/notes.md", "initial\n")
        self._git("add", "src/model.py", "docs/notes.md")
        self._git("commit", "--quiet", "-m", "initial")
        self.source_commit = self._git("rev-parse", "HEAD").stdout.strip()
        self.evidence_path = Path(
            "plans/v0.9-universal-byom/l1-evidence.json"
        )

    def _git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )

    def _write(self, path: str | Path, content: str) -> Path:
        destination = self.repository / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        return destination

    def _write_evidence(
        self,
        value: dict[str, object],
        *,
        commit: bool = True,
    ) -> Path:
        path = self._write(
            self.evidence_path,
            json.dumps(value, sort_keys=True) + "\n",
        )
        if commit:
            self._git("add", self.evidence_path.as_posix())
            self._git("commit", "--quiet", "-m", "record evidence")
        return path

    def _valid_evidence(self, *owned_paths: str) -> dict[str, object]:
        return {
            "source_commit": self.source_commit,
            "owned_paths": list(owned_paths or ("src",)),
        }

    def test_current_evidence_ignores_committed_changes_outside_owned_paths(
        self,
    ) -> None:
        evidence = self._write_evidence(self._valid_evidence("src"))
        initial = check_level_evidence(self.repository, evidence)
        self.assertTrue(initial.is_current)
        self.assertEqual(initial.changed_paths, ())

        self._write("docs/notes.md", "unrelated change\n")
        self._git("add", "docs/notes.md")
        self._git("commit", "--quiet", "-m", "unrelated")
        after_unrelated_change = check_level_evidence(
            self.repository,
            self.evidence_path,
        )
        self.assertTrue(after_unrelated_change.is_current)
        self.assertEqual(after_unrelated_change.owned_paths, ("src",))

    def test_owned_path_change_is_stale_and_main_exits_nonzero(self) -> None:
        self._write_evidence(self._valid_evidence("src"))
        self._write("src/model.py", "VERSION = 2\n")
        self._git("add", "src/model.py")
        self._git("commit", "--quiet", "-m", "change owned source")

        status = check_level_evidence(self.repository, self.evidence_path)
        self.assertFalse(status.is_current)
        self.assertEqual(status.changed_paths, ("src/model.py",))
        stderr = StringIO()
        with redirect_stderr(stderr):
            exit_code = main(
                [
                    "--repo-root",
                    str(self.repository),
                    self.evidence_path.as_posix(),
                ]
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("[STALE]", stderr.getvalue())
        self.assertIn("src/model.py", stderr.getvalue())

    def test_staged_owned_path_change_is_stale(self) -> None:
        evidence = self._write_evidence(self._valid_evidence("src"))
        self._write("src/model.py", "VERSION = 2\n")
        self._git("add", "src/model.py")

        status = check_level_evidence(self.repository, evidence)

        self.assertFalse(status.is_current)
        self.assertEqual(status.changed_paths, ("src/model.py",))

    def test_unstaged_owned_path_change_is_stale(self) -> None:
        evidence = self._write_evidence(self._valid_evidence("src"))
        self._write("src/model.py", "VERSION = 2\n")

        status = check_level_evidence(self.repository, evidence)

        self.assertFalse(status.is_current)
        self.assertEqual(status.changed_paths, ("src/model.py",))

    def test_untracked_owned_path_change_is_stale(self) -> None:
        evidence = self._write_evidence(self._valid_evidence("src"))
        self._write("src/new_model.py", "VERSION = 1\n")

        status = check_level_evidence(self.repository, evidence)

        self.assertFalse(status.is_current)
        self.assertEqual(status.changed_paths, ("src/new_model.py",))

    def test_explicit_owned_file_must_exist_in_source_commit(self) -> None:
        evidence = self._write_evidence(
            self._valid_evidence("src/not-yet-tracked.py")
        )
        self._write("src/not-yet-tracked.py", "VERSION = 1\n")

        with self.assertRaisesRegex(
            StatusCheckError,
            "owned_path_not_in_source_commit",
        ):
            check_level_evidence(self.repository, evidence)

    def test_dirty_paths_outside_owned_scope_do_not_invalidate(self) -> None:
        evidence = self._write_evidence(self._valid_evidence("src"))
        self._write("docs/notes.md", "unstaged unrelated change\n")
        self._write("docs/untracked.md", "untracked unrelated change\n")

        status = check_level_evidence(self.repository, evidence)

        self.assertTrue(status.is_current)
        self.assertEqual(status.changed_paths, ())

    def test_untracked_or_dirty_evidence_file_fails_closed(self) -> None:
        untracked = self._write_evidence(
            self._valid_evidence("src"),
            commit=False,
        )
        with self.assertRaisesRegex(StatusCheckError, "evidence_file_untracked"):
            check_level_evidence(self.repository, untracked)

        self._git("add", self.evidence_path.as_posix())
        self._git("commit", "--quiet", "-m", "record evidence")
        changed = self._valid_evidence("src/model.py")
        self._write_evidence(changed, commit=False)
        with self.assertRaisesRegex(StatusCheckError, "evidence_file_dirty"):
            check_level_evidence(self.repository, self.evidence_path)

        self._git("add", self.evidence_path.as_posix())
        with self.assertRaisesRegex(StatusCheckError, "evidence_file_dirty"):
            check_level_evidence(self.repository, self.evidence_path)

    def test_missing_fields_and_bad_source_commit_fail_closed(self) -> None:
        invalid_values = (
            ({"owned_paths": ["src"]}, "source_commit_missing"),
            ({"source_commit": self.source_commit}, "owned_paths_missing"),
            (
                {"source_commit": "abc", "owned_paths": ["src"]},
                "source_commit_invalid",
            ),
            (
                {"source_commit": self.source_commit, "owned_paths": []},
                "owned_paths_missing",
            ),
            (
                {
                    "source_commit": self.source_commit,
                    "owned_paths": ["src", "src"],
                },
                "owned_paths_duplicate",
            ),
        )
        for value, expected_error in invalid_values:
            with self.subTest(expected_error=expected_error):
                self._write_evidence(value)
                with self.assertRaisesRegex(StatusCheckError, expected_error):
                    check_level_evidence(self.repository, self.evidence_path)

    def test_well_formed_unknown_source_commit_fails_closed(self) -> None:
        self._write_evidence(
            {"source_commit": "f" * 40, "owned_paths": ["src"]}
        )
        with self.assertRaisesRegex(StatusCheckError, "source_commit_not_found"):
            check_level_evidence(self.repository, self.evidence_path)

    def test_owned_path_traversal_absolute_and_pathspec_magic_fail_closed(
        self,
    ) -> None:
        invalid_paths = (
            "../escape",
            "src/../../escape",
            "/tmp/escape",
            "C:/escape",
            "src\\model.py",
            ":(glob)**",
            ".git/config",
            "./src",
        )
        for invalid_path in invalid_paths:
            with self.subTest(path=invalid_path):
                self._write_evidence(self._valid_evidence(invalid_path))
                with self.assertRaises(StatusCheckError):
                    check_level_evidence(self.repository, self.evidence_path)

    def test_symlinked_owned_path_and_evidence_cannot_escape_repository(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (self.repository / "external").symlink_to(outside, target_is_directory=True)
        self._write_evidence(self._valid_evidence("external/model.py"))
        with self.assertRaisesRegex(
            StatusCheckError,
            "owned_path_outside_repository",
        ):
            check_level_evidence(self.repository, self.evidence_path)

        outside_evidence = outside / "l1-evidence.json"
        outside_evidence.write_text(
            json.dumps(self._valid_evidence("src")),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            StatusCheckError,
            "evidence_path_outside_repository",
        ):
            check_level_evidence(self.repository, outside_evidence)

    def test_non_repository_and_nested_directory_are_rejected(self) -> None:
        non_repository = Path(self.temporary.name) / "not-a-repository"
        non_repository.mkdir()
        with self.assertRaisesRegex(StatusCheckError, "not_a_git_repository"):
            validate_repository(non_repository)
        with self.assertRaisesRegex(StatusCheckError, "repository_root_required"):
            validate_repository(self.repository / "src")

    def test_default_discovery_fails_when_no_level_evidence_exists(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr):
            exit_code = main(["--repo-root", str(self.repository)])
        self.assertEqual(exit_code, 2)
        self.assertIn("no_level_evidence_found", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
