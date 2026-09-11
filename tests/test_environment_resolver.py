from __future__ import annotations

import base64
import unittest

from model_harness.environment_resolver import resolve_environment_dependencies


HASH = "a" * 64


def snapshot(path: str, content: str) -> dict:
    return {
        "documents": [
            {
                "path": path,
                "content_base64": base64.b64encode(content.encode()).decode(),
            }
        ]
    }


class EnvironmentResolverTests(unittest.TestCase):
    def test_hashed_requirements_create_server_owned_packages(self) -> None:
        result = resolve_environment_dependencies(
            snapshot=snapshot(
                "requirements.txt",
                f"torch==2.5.1 --hash=sha256:{HASH}\n",
            ),
            analysis={
                "dependency_files": [
                    {"path": "requirements.txt", "kind": "pip-requirements"}
                ]
            },
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["packages"][0]["name"], "torch")
        self.assertEqual(result["packages"][0]["version"], "2.5.1")
        self.assertEqual(result["packages"][0]["hashes"], [f"sha256:{HASH}"])

    def test_unpinned_or_unhashed_requirement_blocks_lock(self) -> None:
        result = resolve_environment_dependencies(
            snapshot=snapshot("requirements.txt", "torch>=2\ntransformers==4.1\n"),
            analysis={
                "dependency_files": [
                    {"path": "requirements.txt", "kind": "pip-requirements"}
                ]
            },
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(len(result["unresolved"]), 2)
        self.assertEqual(result["packages"], [])

    def test_hash_option_inside_inline_comment_never_authorizes_lock(self) -> None:
        result = resolve_environment_dependencies(
            snapshot=snapshot(
                "requirements.txt",
                f"torch==2.5.1  # --hash=sha256:{HASH}\n",
            ),
            analysis={
                "dependency_files": [
                    {"path": "requirements.txt", "kind": "pip-requirements"}
                ]
            },
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["packages"], [])
        self.assertEqual(
            result["unresolved"][0]["code"],
            "dependency_not_exactly_pinned_and_hashed",
        )
        self.assertNotIn("--hash", result["unresolved"][0]["observed"])

    def test_valid_hash_before_inline_comment_remains_enforced(self) -> None:
        result = resolve_environment_dependencies(
            snapshot=snapshot(
                "requirements.txt",
                f"torch==2.5.1 --hash=sha256:{HASH}  # locked export\n",
            ),
            analysis={
                "dependency_files": [
                    {"path": "requirements.txt", "kind": "pip-requirements"}
                ]
            },
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["packages"][0]["hashes"], [f"sha256:{HASH}"])

    def test_missing_dependency_manifest_fails_closed(self) -> None:
        result = resolve_environment_dependencies(
            snapshot={"documents": []},
            analysis={"dependency_files": []},
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["packages"], [])
        self.assertEqual(
            result["unresolved"][0]["code"],
            "dependency_manifest_missing",
        )

    def test_extra_tokens_markers_and_index_options_fail_closed(self) -> None:
        invalid_lines = (
            f"torch==2.5.1 unexpected-token --hash=sha256:{HASH}\n",
            f'torch==2.5.1; python_version < "0" --hash=sha256:{HASH}\n',
            f"torch==2.5.1 --trusted-host evil.example --hash=sha256:{HASH}\n",
        )
        for line in invalid_lines:
            with self.subTest(line=line):
                result = resolve_environment_dependencies(
                    snapshot=snapshot("requirements.txt", line),
                    analysis={
                        "dependency_files": [
                            {
                                "path": "requirements.txt",
                                "kind": "pip-requirements",
                            }
                        ]
                    },
                )
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["packages"], [])
                self.assertEqual(
                    result["unresolved"][0]["code"],
                    "dependency_not_exactly_pinned_and_hashed",
                )

    def test_unfinished_continuation_fails_closed(self) -> None:
        result = resolve_environment_dependencies(
            snapshot=snapshot(
                "requirements.txt",
                f"torch==2.5.1 --hash=sha256:{HASH} \\",
            ),
            analysis={
                "dependency_files": [
                    {"path": "requirements.txt", "kind": "pip-requirements"}
                ]
            },
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["packages"], [])

    def test_project_metadata_without_exported_lock_is_blocked(self) -> None:
        result = resolve_environment_dependencies(
            snapshot=snapshot("pyproject.toml", "[project]\ndependencies=['torch']"),
            analysis={
                "dependency_files": [
                    {"path": "pyproject.toml", "kind": "pyproject"}
                ]
            },
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(
            result["unresolved"][0]["code"],
            "dependency_manifest_requires_lock_export",
        )

    def test_evidence_uses_physical_line_number_for_logical_requirement(self) -> None:
        result = resolve_environment_dependencies(
            snapshot=snapshot(
                "requirements.txt",
                f"# frozen lock\n\ntorch==2.5.1 \\\n    --hash=sha256:{HASH}\n",
            ),
            analysis={
                "dependency_files": [
                    {"path": "requirements.txt", "kind": "pip-requirements"}
                ]
            },
        )

        self.assertEqual(result["status"], "ready")
        self.assertIn("requirements.txt:L3", result["evidence_refs"])


if __name__ == "__main__":
    unittest.main()
