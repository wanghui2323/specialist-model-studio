from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from model_harness.github_source import (
    GITHUB_API_ORIGIN,
    GitHubRestTransport,
    GitHubSourceProvider,
)
from model_harness.huggingface_source import HuggingFaceSourceProvider
from model_harness.model_sources import (
    MAX_DOCUMENT_BYTES,
    MAX_PROVIDER_RESPONSE_BYTES,
    ModelSourceIncompleteError,
    ModelSourceUpstreamError,
    ModelSourceValidationError,
    RemoteSourceFile,
    SourceProvider,
    SourceSnapshot,
    collect_source_documents,
    parse_model_source_reference,
    source_candidate_id,
    tree_manifest_sha256,
    verify_source_snapshot,
)


COMMIT = "a" * 40
TREE = "b" * 40


def _git_blob_sha(content: bytes) -> str:
    return hashlib.sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()


class FakeGitHubTransport:
    def __init__(
        self,
        *,
        truncated: bool = False,
        resolved_commit: str = COMMIT,
        spdx_id: str = "Apache-2.0",
        include_submodule: bool = False,
        weight_blob: bytes | None = None,
        tamper_blob_path: str | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.truncated = truncated
        self.resolved_commit = resolved_commit
        self.spdx_id = spdx_id
        self.include_submodule = include_submodule
        self.tamper_blob_path = tamper_blob_path
        self.documents = {
            "README.md": b"# fixture\nNo code is executed.\n",
            "scripts/finetune.py": b"raise RuntimeError('repository code was executed')\n",
        }
        if weight_blob is not None:
            self.documents["weights/model.safetensors"] = weight_blob

    def request_json(self, path, *, query=None, token=None, max_bytes=None):
        self.calls.append(
            {
                "path": path,
                "query": dict(query or {}),
                "token_present": token is not None,
                "max_bytes": max_bytes,
            }
        )
        if path == "/search/repositories":
            return {
                "items": [
                    {
                        "full_name": "fixture/trainer",
                        "default_branch": "stable",
                        "description": "Small training fixture",
                        "license": {"spdx_id": "MIT"},
                        "stargazers_count": 42,
                        "size": 128,
                    }
                ]
            }
        if "/commits/" in path:
            return {
                "sha": self.resolved_commit,
                "commit": {"tree": {"sha": TREE}},
            }
        if path.endswith("/license"):
            return {"license": {"spdx_id": self.spdx_id}}
        if "/git/trees/" in path:
            tree = [
                {
                    "path": "README.md",
                    "mode": "100644",
                    "type": "blob",
                    "size": len(self.documents["README.md"]),
                    "sha": _git_blob_sha(self.documents["README.md"]),
                },
                {
                    "path": "scripts/finetune.py",
                    "mode": "100644",
                    "type": "blob",
                    "size": len(self.documents["scripts/finetune.py"]),
                    "sha": _git_blob_sha(self.documents["scripts/finetune.py"]),
                },
                {
                    "path": "scripts/run.sh",
                    "mode": "100755",
                    "type": "blob",
                    "size": 20,
                    "sha": "e" * 40,
                },
                {
                    "path": "current-model",
                    "mode": "120000",
                    "type": "blob",
                    "size": 12,
                    "sha": "f" * 40,
                },
            ]
            if "weights/model.safetensors" in self.documents:
                content = self.documents["weights/model.safetensors"]
                tree.append(
                    {
                        "path": "weights/model.safetensors",
                        "mode": "100644",
                        "type": "blob",
                        "size": len(content),
                        "sha": _git_blob_sha(content),
                    }
                )
            for document_path, content in self.documents.items():
                if document_path in {
                    "README.md",
                    "scripts/finetune.py",
                    "weights/model.safetensors",
                }:
                    continue
                tree.append(
                    {
                        "path": document_path,
                        "mode": "100644",
                        "type": "blob",
                        "size": len(content),
                        "sha": _git_blob_sha(content),
                    }
                )
            if self.include_submodule:
                tree.append(
                    {
                        "path": "vendor/library",
                        "mode": "160000",
                        "type": "commit",
                        "sha": "1" * 40,
                    }
                )
            return {
                "sha": TREE,
                "truncated": self.truncated,
                "tree": tree,
            }
        if "/git/blobs/" in path:
            digest = path.rsplit("/", 1)[-1]
            selected_path = next(
                document_path
                for document_path, content in self.documents.items()
                if _git_blob_sha(content) == digest
            )
            content = self.documents[selected_path]
            if selected_path == self.tamper_blob_path:
                content = bytes([content[0] ^ 1]) + content[1:]
            return {
                "sha": digest,
                "size": len(content),
                "encoding": "base64",
                "content": base64.b64encode(content).decode("ascii"),
            }
        raise AssertionError(f"unexpected GitHub path: {path}")


class _FakeResponse:
    def __init__(self, body: bytes, *, content_length: int | None = None) -> None:
        self.body = body
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def getcode(self):
        return 200

    def read(self, amount):
        return self.body[:amount]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _RecordingOpener:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return self.response


class FakeHfApi:
    def __init__(self, documents: dict[str, bytes]) -> None:
        self.documents = documents
        self.tokens: list[bool] = []

    def model_info(self, **kwargs):
        self.tokens.append(kwargs.get("token") is not None)
        return SimpleNamespace(
            id="fixture/model",
            sha=COMMIT,
            card_data={"license": "apache-2.0"},
            library_name="transformers",
            pipeline_tag="text-classification",
            tags=["transformers", "text-classification"],
        )

    def list_models(self, **kwargs):
        self.tokens.append(kwargs.get("token") is not None)
        return [
            SimpleNamespace(
                id="fixture/model",
                sha=COMMIT,
                card_data={"license": "apache-2.0"},
                library_name="transformers",
                pipeline_tag="text-classification",
                downloads=123,
                likes=7,
            )
        ]

    def list_repo_tree(self, **kwargs):
        self.tokens.append(kwargs.get("token") is not None)
        return [
            SimpleNamespace(
                path="README.md",
                size=len(self.documents["README.md"]),
                blob_id=_git_blob_sha(self.documents["README.md"]),
                lfs=None,
            ),
            SimpleNamespace(
                path="train.py",
                size=len(self.documents["train.py"]),
                blob_id=_git_blob_sha(self.documents["train.py"]),
                lfs=None,
            ),
            SimpleNamespace(
                path="model.safetensors",
                size=900_000_000,
                blob_id="c" * 40,
                lfs={"sha256": "d" * 64, "size": 900_000_000},
            ),
            SimpleNamespace(path="scripts", tree_id="e" * 40),
        ]


class ModelSourceProviderTests(unittest.TestCase):
    def test_official_search_results_are_candidate_only_until_resolution(self) -> None:
        github = GitHubSourceProvider(transport=FakeGitHubTransport())
        github_result = github.search("text classification training", limit=3)
        self.assertEqual(github_result[0]["repository"], "fixture/trainer")
        self.assertIsNone(github_result[0]["resolved_commit"])
        self.assertEqual(github_result[0]["license"], "MIT")
        self.assertEqual(
            github_result[0]["candidate_id"],
            source_candidate_id("github", "fixture/trainer", "stable"),
        )

        documents = {"README.md": b"# fixture\n", "train.py": b"pass\n"}
        api = FakeHfApi(documents)
        huggingface = HuggingFaceSourceProvider(
            api_factory=lambda token=None: api,
            hf_hub_download_fn=lambda **kwargs: "unused",
        )
        hf_result = huggingface.search(
            "text classification",
            pipeline_tag="text-classification",
            token="ephemeral-hf",
        )
        self.assertEqual(hf_result[0]["repository"], "fixture/model")
        self.assertEqual(hf_result[0]["resolved_commit"], COMMIT)
        self.assertEqual(hf_result[0]["catalog_evidence"], "huggingface_official_hub_api")
        self.assertNotIn("ephemeral-hf", repr(hf_result))

    def test_github_lfs_pointer_is_never_treated_as_static_document_content(self) -> None:
        transport = FakeGitHubTransport()
        transport.documents["README.md"] = (
            b"version https://git-lfs.github.com/spec/v1\n"
            b"oid sha256:" + b"a" * 64 + b"\nsize 1234\n"
        )
        provider = GitHubSourceProvider(transport=transport)
        source = provider.resolve("fixture/trainer", "stable")
        readme = next(
            item for item in provider.list_tree(source) if item.path == "README.md"
        )
        with self.assertRaisesRegex(
            ModelSourceIncompleteError,
            "github_lfs_pointer_requires_object_metadata",
        ):
            provider.read_document(source, readme)

    def test_github_typical_weight_lfs_pointer_records_object_integrity(self) -> None:
        pointer = (
            b"version https://git-lfs.github.com/spec/v1\n"
            b"oid sha256:" + b"a" * 64 + b"\nsize 900000000\n"
        )
        transport = FakeGitHubTransport(weight_blob=pointer)
        provider = GitHubSourceProvider(transport=transport)
        source = provider.resolve("fixture/trainer", "stable")
        files = provider.list_tree(source)
        weight = next(
            item for item in files if item.path == "weights/model.safetensors"
        )
        self.assertEqual(weight.remote_digest, _git_blob_sha(pointer))
        self.assertEqual(weight.lfs_sha256, "a" * 64)
        self.assertEqual(weight.size_bytes, 900_000_000)

    def test_gitattributes_discovers_non_weight_lfs_dataset_pointer(self) -> None:
        pointer = (
            b"version https://git-lfs.github.com/spec/v1\n"
            b"oid sha256:" + b"a" * 64 + b"\nsize 9000000000\n"
        )
        transport = FakeGitHubTransport()
        transport.documents[".gitattributes"] = (
            b"*.zip filter=lfs diff=lfs merge=lfs -text\n"
        )
        transport.documents["data/archive.zip"] = pointer
        provider = GitHubSourceProvider(transport=transport)
        source = provider.resolve("fixture/trainer", "stable")
        files = provider.list_tree(source)

        archive = next(
            item
            for item in files
            if item.path == "data/archive.zip"
        )

        self.assertEqual(archive.lfs_sha256, "a" * 64)
        self.assertEqual(archive.size_bytes, 9_000_000_000)
        self.assertEqual(
            {item.path for item in collect_source_documents(provider, source, files)},
            {"README.md", "scripts/finetune.py"},
        )

    def test_unsupported_gitattributes_lfs_quote_or_macro_fails_closed(self) -> None:
        pointer = (
            b"version https://git-lfs.github.com/spec/v1\n"
            b"oid sha256:" + b"a" * 64 + b"\nsize 9000000000\n"
        )
        cases = (
            (
                b'"data/my file.zip" filter=lfs diff=lfs merge=lfs -text\n',
                "data/my file.zip",
            ),
            (b"[attr]large filter=lfs diff=lfs merge=lfs -text\n*.zip large\n", "data/archive.zip"),
        )
        for attributes, path in cases:
            with self.subTest(attributes=attributes):
                transport = FakeGitHubTransport()
                transport.documents[".gitattributes"] = attributes
                transport.documents[path] = pointer
                provider = GitHubSourceProvider(transport=transport)
                source = provider.resolve("fixture/trainer", "stable")
                with self.assertRaisesRegex(
                    ModelSourceIncompleteError,
                    "github_gitattributes_lfs_pattern_unsupported",
                ):
                    provider.list_tree(source)

    def test_github_malformed_lfs_pointer_fails_closed(self) -> None:
        malformed_pointer = (
            b"version https://git-lfs.github.com/spec/v1\n"
            b"oid sha256:not-a-sha256\nsize 1234\n"
        )
        provider = GitHubSourceProvider(
            transport=FakeGitHubTransport(weight_blob=malformed_pointer)
        )
        source = provider.resolve("fixture/trainer", "stable")
        with self.assertRaisesRegex(
            ModelSourceIncompleteError,
            "github_lfs_pointer_invalid",
        ):
            provider.list_tree(source)

    def test_github_decoded_blob_tamper_fails_git_object_verification(self) -> None:
        transport = FakeGitHubTransport(tamper_blob_path="README.md")
        provider = GitHubSourceProvider(transport=transport)
        source = provider.resolve("fixture/trainer", "stable")
        files = provider.list_tree(source)
        with self.assertRaisesRegex(
            ModelSourceUpstreamError,
            "github_blob_content_digest_mismatch",
        ):
            collect_source_documents(provider, source, files)

    def test_github_submodule_fails_closed_before_blob_download(self) -> None:
        transport = FakeGitHubTransport(include_submodule=True)
        provider = GitHubSourceProvider(transport=transport)
        source = provider.resolve("fixture/trainer", "stable")
        with self.assertRaisesRegex(
            ModelSourceIncompleteError,
            "github_submodule_incomplete",
        ):
            provider.list_tree(source)
        self.assertFalse(
            any("/git/blobs/" in str(call["path"]) for call in transport.calls)
        )

    def test_public_source_reference_parser_rejects_ambiguous_or_credentialed_urls(self) -> None:
        self.assertEqual(
            parse_model_source_reference(
                "https://github.com/fixture/trainer/tree/release-v1"
            ),
            {
                "provider": "github",
                "repository": "fixture/trainer",
                "requested_revision": "release-v1",
            },
        )
        self.assertEqual(
            parse_model_source_reference(
                "fixture/model", provider_hint="huggingface"
            )["repository"],
            "fixture/model",
        )
        for value in (
            "fixture/model",
            "https://token@github.com/fixture/trainer",
            "https://github.com/fixture/trainer?token=secret",
            "https://evil.example/fixture/trainer",
        ):
            with self.subTest(value=value), self.assertRaises(
                ModelSourceValidationError
            ):
                parse_model_source_reference(value)

    def test_github_resolves_branch_lists_risks_and_reads_only_safe_documents(
        self,
    ) -> None:
        transport = FakeGitHubTransport()
        provider = GitHubSourceProvider(transport=transport)
        self.assertIsInstance(provider, SourceProvider)
        source = provider.resolve("fixture/model", "main", token="ephemeral-gh")
        self.assertEqual(source.resolved_commit, COMMIT)
        self.assertEqual(source.tree_reference, TREE)
        self.assertEqual(source.license_status, "known")
        files = provider.list_tree(source, token="ephemeral-gh")
        self.assertEqual(
            {item.kind for item in files},
            {"blob", "executable", "symlink"},
        )
        documents = collect_source_documents(
            provider,
            source,
            files,
            token="ephemeral-gh",
        )
        self.assertEqual(
            {item.path for item in documents},
            {"README.md", "scripts/finetune.py"},
        )
        self.assertIn(b"repository code was executed", documents[1].content)
        requested_blobs = {
            str(call["path"]).rsplit("/", 1)[-1]
            for call in transport.calls
            if "/git/blobs/" in str(call["path"])
        }
        self.assertEqual(
            requested_blobs,
            {
                _git_blob_sha(transport.documents["README.md"]),
                _git_blob_sha(transport.documents["scripts/finetune.py"]),
            },
        )
        self.assertNotIn("ephemeral-gh", repr(source.to_dict()))
        self.assertNotIn("ephemeral-gh", repr(provider))

    def test_github_tree_truncation_fails_closed(self) -> None:
        provider = GitHubSourceProvider(transport=FakeGitHubTransport(truncated=True))
        source = provider.resolve("fixture/model", "main")
        with self.assertRaisesRegex(
            ModelSourceIncompleteError, "github_tree_truncated"
        ):
            provider.list_tree(source)

    def test_analysis_document_count_and_total_size_limits_fail_before_download(
        self,
    ) -> None:
        transport = FakeGitHubTransport()
        provider = GitHubSourceProvider(transport=transport)
        source = provider.resolve("fixture/model", "main")
        too_many = tuple(
            RemoteSourceFile(
                path=f"scripts/run_{index:02d}.py",
                kind="blob",
                mode="100644",
                size_bytes=1,
                remote_digest=hashlib.sha1(str(index).encode("ascii")).hexdigest(),
            )
            for index in range(65)
        )
        with self.assertRaisesRegex(
            ModelSourceValidationError,
            "analysis_document_count_limit_exceeded",
        ):
            collect_source_documents(provider, source, too_many)
        too_large = tuple(
            RemoteSourceFile(
                path=f"scripts/run_{index:02d}.py",
                kind="blob",
                mode="100644",
                size_bytes=MAX_DOCUMENT_BYTES,
                remote_digest=hashlib.sha1(
                    f"large-{index}".encode("ascii")
                ).hexdigest(),
            )
            for index in range(9)
        )
        with self.assertRaisesRegex(
            ModelSourceValidationError,
            "document_total_size_limit_exceeded",
        ):
            collect_source_documents(provider, source, too_large)
        self.assertFalse(
            any("/git/blobs/" in str(call["path"]) for call in transport.calls)
        )

    def test_github_commit_and_inputs_fail_closed(self) -> None:
        provider = GitHubSourceProvider(
            transport=FakeGitHubTransport(resolved_commit="f" * 40)
        )
        with self.assertRaisesRegex(
            ModelSourceUpstreamError, "resolved_commit_mismatch"
        ):
            provider.resolve("fixture/model", COMMIT)
        for repository in (
            "https://github.com/fixture/model",
            "fixture/model/extra",
            "../model",
        ):
            with self.subTest(repository=repository):
                with self.assertRaises(ModelSourceValidationError):
                    provider.resolve(repository, "main")
        for revision in ("../main", "feature//unsafe", " main", "main@{1}"):
            with self.subTest(revision=revision):
                with self.assertRaises(ModelSourceValidationError):
                    provider.resolve("fixture/model", revision)
        unknown = GitHubSourceProvider(
            transport=FakeGitHubTransport(spdx_id="NOASSERTION")
        ).resolve("fixture/model", "main")
        self.assertEqual(
            (unknown.license, unknown.license_status),
            ("unknown", "unknown"),
        )

    def test_github_rest_transport_pins_origin_and_enforces_response_limit(
        self,
    ) -> None:
        body = json.dumps({"ok": True}).encode("utf-8")
        opener = _RecordingOpener(_FakeResponse(body, content_length=len(body)))
        transport = GitHubRestTransport(opener=opener)
        self.assertEqual(
            transport.request_json(
                "/repos/fixture/model/commits/main",
                query={"page": "1"},
                token="gh-token",
            ),
            {"ok": True},
        )
        request, timeout = opener.requests[0]
        self.assertTrue(request.full_url.startswith(GITHUB_API_ORIGIN + "/repos/"))
        self.assertIn("Authorization", dict(request.header_items()))
        self.assertEqual(timeout, 15.0)
        oversized = _RecordingOpener(
            _FakeResponse(b"{}", content_length=MAX_PROVIDER_RESPONSE_BYTES + 1)
        )
        with self.assertRaisesRegex(
            ModelSourceUpstreamError,
            "github_response_size_limit_exceeded",
        ):
            GitHubRestTransport(opener=oversized).request_json(
                "/repos/fixture/model/commits/main"
            )
        for unsafe_path in (
            "https://evil.example/repos/x/y",
            "//evil.example/repos/x/y",
            "/repos/x/y?redirect=https://evil.example",
        ):
            with self.subTest(path=unsafe_path):
                with self.assertRaises(ModelSourceValidationError):
                    transport.request_json(unsafe_path)

    def test_huggingface_resolves_fixed_commit_and_never_executes_documents(
        self,
    ) -> None:
        documents = {
            "README.md": b"# Hugging Face fixture\n",
            "train.py": b"raise RuntimeError('this must remain inert')\n",
        }
        api = FakeHfApi(documents)
        seen_download_tokens: list[bool] = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, content in documents.items():
                (root / name).write_bytes(content)

            def download(**kwargs):
                seen_download_tokens.append(kwargs.get("token") is not None)
                return str(root / kwargs["filename"])

            provider = HuggingFaceSourceProvider(
                api_factory=lambda token=None: api,
                hf_hub_download_fn=download,
            )
            self.assertIsInstance(provider, SourceProvider)
            source = provider.resolve(
                "fixture/model",
                "main",
                token="ephemeral-hf",
            )
            files = provider.list_tree(source, token="ephemeral-hf")
            collected = collect_source_documents(
                provider,
                source,
                files,
                token="ephemeral-hf",
            )
        self.assertEqual(source.resolved_commit, COMMIT)
        self.assertEqual(source.license_status, "known")
        self.assertEqual({item.path for item in collected}, {"README.md", "train.py"})
        self.assertIn(
            b"must remain inert",
            next(item for item in collected if item.path == "train.py").content,
        )
        self.assertNotIn("model.safetensors", {item.path for item in collected})
        self.assertEqual(api.tokens, [True, True])
        self.assertEqual(seen_download_tokens, [True, True])
        self.assertNotIn("ephemeral-hf", repr(source.to_dict()))
        self.assertNotIn("ephemeral-hf", repr(provider))

    def test_huggingface_commit_mismatch_lfs_and_digest_checks_fail_closed(
        self,
    ) -> None:
        documents = {"README.md": b"# fixture\n", "train.py": b"pass\n"}
        api = FakeHfApi(documents)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "README.md"
            path.write_bytes(documents["README.md"])
            provider = HuggingFaceSourceProvider(
                api_factory=lambda token=None: api,
                hf_hub_download_fn=lambda **kwargs: str(path),
            )
            with self.assertRaisesRegex(
                ModelSourceUpstreamError, "resolved_commit_mismatch"
            ):
                provider.resolve("fixture/model", "f" * 40)
            source = provider.resolve("fixture/model", "main")
            lfs_file = RemoteSourceFile(
                path="model.safetensors",
                kind="blob",
                mode=None,
                size_bytes=900_000_000,
                remote_digest="c" * 40,
                lfs_sha256="d" * 64,
            )
            with self.assertRaisesRegex(
                ModelSourceValidationError,
                "huggingface_document_not_readable",
            ):
                provider.read_document(source, lfs_file)
            bad_digest = RemoteSourceFile(
                path="README.md",
                kind="blob",
                mode=None,
                size_bytes=len(documents["README.md"]),
                remote_digest="c" * 40,
            )
            with self.assertRaisesRegex(
                ModelSourceValidationError,
                "huggingface_document_digest_mismatch",
            ):
                provider.read_document(source, bad_digest)

    def test_snapshot_integrity_binds_tree_documents_and_execution_policy(self) -> None:
        transport = FakeGitHubTransport()
        provider = GitHubSourceProvider(transport=transport)
        source = provider.resolve("fixture/model", "main")
        files = provider.list_tree(source)
        documents = collect_source_documents(provider, source, files)
        snapshot = SourceSnapshot(
            schema_version="0.1",
            snapshot_id="source-fixture",
            task_id="task-fixture",
            resolution_id="resolution-fixture",
            provider=source.provider,
            repository=source.repository,
            requested_revision=source.requested_revision,
            resolved_commit=source.resolved_commit,
            license=source.license,
            license_status=source.license_status,
            files=files,
            documents=documents,
            tree_manifest_sha256=tree_manifest_sha256(files),
            execution_policy="never_execute_in_l1",
            created_at_utc="2026-08-23T00:00:00+00:00",
        )
        self.assertEqual(verify_source_snapshot(snapshot), ())
        self.assertEqual(
            verify_source_snapshot(replace(snapshot, tree_manifest_sha256="0" * 64)),
            ("tree_manifest_sha256_mismatch",),
        )
        self.assertIn(
            "unsafe_execution_policy",
            verify_source_snapshot(replace(snapshot, execution_policy="execute")),
        )


if __name__ == "__main__":
    unittest.main()
