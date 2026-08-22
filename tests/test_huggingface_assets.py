from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from model_harness.huggingface_assets import (
    HuggingFaceAssetError,
    HuggingFaceCapabilityUnavailable,
    HuggingFaceHubDownloader,
    _HubBindings,
    download_huggingface_asset,
    resolve_training_asset,
)
from model_harness.model_assets import ModelAssetDownloader, ModelAssetError, ModelAssetStore


COMMIT = "c" * 40


def _safetensors_bytes() -> bytes:
    header = json.dumps(
        {"weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}},
        separators=(",", ":"),
    ).encode("utf-8")
    return len(header).to_bytes(8, "little") + header + struct.pack("<f", 2.0)


def _write_snapshot(root: Path) -> Path:
    snapshot = root / "snapshot"
    (snapshot / "tokenizer").mkdir(parents=True)
    (snapshot / "config.json").write_text('{"model_type":"fixture"}', encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(_safetensors_bytes())
    (snapshot / "tokenizer" / "tokenizer.json").write_text(
        '{"version":"1.0"}', encoding="utf-8"
    )
    (snapshot / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (snapshot / "pytorch_model.bin").write_bytes(b"unsafe pickle-like legacy file")
    (snapshot / "run.py").write_text("raise SystemExit\n", encoding="utf-8")
    return snapshot


class FakeApi:
    def __init__(self, info: Any, calls: list[dict[str, Any]], token: str | None) -> None:
        self.info = info
        self.calls = calls
        self.token_seen = token is not None

    def model_info(self, **kwargs: Any) -> Any:
        self.calls.append(
            {
                "repo_id": kwargs["repo_id"],
                "revision": kwargs["revision"],
                "files_metadata": kwargs["files_metadata"],
                "token_seen": kwargs.get("token") is not None,
            }
        )
        return self.info


def _disk_bytes(root: Path) -> bytes:
    result = bytearray()
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            result.extend(path.read_bytes())
    return bytes(result)


class HuggingFaceAssetTests(unittest.TestCase):
    def test_official_semantics_are_commit_pinned_allowlisted_and_consumable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = _write_snapshot(root)
            info = SimpleNamespace(
                sha=COMMIT,
                siblings=[
                    SimpleNamespace(rfilename=".gitattributes"),
                    SimpleNamespace(rfilename="config.json"),
                    SimpleNamespace(rfilename="model.safetensors"),
                    SimpleNamespace(rfilename="tokenizer/tokenizer.json"),
                    SimpleNamespace(rfilename="README.md"),
                    SimpleNamespace(rfilename="pytorch_model.bin"),
                    SimpleNamespace(rfilename="run.py"),
                ],
                card_data={"license": "apache-2.0"},
            )
            api_calls: list[dict[str, Any]] = []
            snapshot_calls: list[dict[str, Any]] = []

            def api_factory(*, token: str | None) -> FakeApi:
                return FakeApi(info, api_calls, token)

            def snapshot_download(**kwargs: Any) -> str:
                snapshot_calls.append(
                    {
                        "repo_id": kwargs["repo_id"],
                        "repo_type": kwargs["repo_type"],
                        "revision": kwargs["revision"],
                        "allow_patterns": kwargs["allow_patterns"],
                        "token_seen": kwargs.get("token") is not None,
                    }
                )
                return str(snapshot)

            downloader = HuggingFaceHubDownloader(
                api_factory=api_factory,
                snapshot_download_fn=snapshot_download,
            )
            self.assertIsInstance(downloader, ModelAssetDownloader)
            self.assertTrue(downloader.capability()["available"])
            store_root = root / "assets"
            store = ModelAssetStore(store_root)
            token = "hf_ephemeral_fixture_token"
            asset = download_huggingface_asset(
                store,
                repo_id="fixture/tiny-model",
                commit=COMMIT,
                token=token,
                downloader=downloader,
            )

            self.assertEqual(asset.resolved_commit, COMMIT)
            self.assertEqual(asset.license, "apache-2.0")
            self.assertEqual(asset.provider, "huggingface")
            self.assertEqual(len(api_calls), 1)
            self.assertEqual(
                api_calls[0],
                {
                    "repo_id": "fixture/tiny-model",
                    "revision": COMMIT,
                    "files_metadata": True,
                    "token_seen": True,
                },
            )
            self.assertEqual(len(snapshot_calls), 1)
            self.assertEqual(snapshot_calls[0]["repo_type"], "model")
            self.assertEqual(snapshot_calls[0]["revision"], COMMIT)
            self.assertTrue(snapshot_calls[0]["token_seen"])
            self.assertIn("*.safetensors", snapshot_calls[0]["allow_patterns"])
            self.assertNotIn(token.encode(), _disk_bytes(store_root))
            self.assertFalse(hasattr(downloader, "token"))

            handle = resolve_training_asset(
                store,
                asset.asset_id,
                required_files=("config.json", "model.safetensors"),
            )
            self.assertEqual(handle.asset.asset_id, asset.asset_id)
            self.assertEqual(handle.file("config.json").parent, handle.root)
            self.assertEqual(handle.model_files, (handle.root / "model.safetensors",))
            copied = {relative for relative, _ in handle.files}
            self.assertNotIn("pytorch_model.bin", copied)
            self.assertNotIn("run.py", copied)

    def test_missing_optional_dependency_is_an_explicit_capability(self) -> None:
        def unavailable() -> _HubBindings:
            raise HuggingFaceCapabilityUnavailable(
                "capability_unavailable:huggingface_hub"
            )

        downloader = HuggingFaceHubDownloader(bindings_loader=unavailable)
        capability = downloader.capability()
        self.assertFalse(capability["available"])
        self.assertEqual(capability["reason"], "capability_unavailable:huggingface_hub")
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                HuggingFaceCapabilityUnavailable,
                "capability_unavailable:huggingface_hub",
            ):
                downloader.download(
                    provider="huggingface",
                    repo_id="fixture/model",
                    revision=COMMIT,
                    destination=Path(temporary),
                    allow_patterns=("*.safetensors",),
                    token=None,
                )
            with self.assertRaisesRegex(
                HuggingFaceCapabilityUnavailable,
                "capability_unavailable:huggingface_hub",
            ):
                download_huggingface_asset(
                    ModelAssetStore(Path(temporary) / "assets"),
                    repo_id="fixture/model",
                    commit=COMMIT,
                    downloader=downloader,
                )

    def test_api_resolved_commit_must_match_requested_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = _write_snapshot(root)
            info = SimpleNamespace(
                sha="d" * 40,
                siblings=[SimpleNamespace(rfilename="model.safetensors")],
                card_data={"license": "mit"},
            )
            downloader = HuggingFaceHubDownloader(
                api_factory=lambda token: FakeApi(info, [], token),
                snapshot_download_fn=lambda **kwargs: str(snapshot),
            )
            destination = root / "destination"
            destination.mkdir()
            with self.assertRaisesRegex(HuggingFaceAssetError, "resolved_commit_mismatch"):
                downloader.download(
                    provider="huggingface",
                    repo_id="fixture/model",
                    revision=COMMIT,
                    destination=destination,
                    allow_patterns=("*.safetensors",),
                    token=None,
                )

    def test_api_path_traversal_is_rejected_before_snapshot_download(self) -> None:
        info = SimpleNamespace(
            sha=COMMIT,
            siblings=[SimpleNamespace(rfilename="../model.safetensors")],
            card_data={"license": "mit"},
        )
        snapshot_called = False

        def snapshot_download(**kwargs: Any) -> str:
            nonlocal snapshot_called
            snapshot_called = True
            return "."

        downloader = HuggingFaceHubDownloader(
            api_factory=lambda token: FakeApi(info, [], token),
            snapshot_download_fn=snapshot_download,
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                HuggingFaceAssetError, "unsafe_huggingface_repo_path"
            ):
                downloader.download(
                    provider="huggingface",
                    repo_id="fixture/model",
                    revision=COMMIT,
                    destination=Path(temporary),
                    allow_patterns=("*.safetensors",),
                    token=None,
                )
        self.assertFalse(snapshot_called)

    def test_snapshot_symlink_cannot_escape_repository_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            outside = root / "outside.safetensors"
            outside.write_bytes(_safetensors_bytes())
            (snapshot / "model.safetensors").symlink_to(outside)
            info = SimpleNamespace(
                sha=COMMIT,
                siblings=[SimpleNamespace(rfilename="model.safetensors")],
                card_data={"license": "mit"},
            )
            downloader = HuggingFaceHubDownloader(
                api_factory=lambda token: FakeApi(info, [], token),
                snapshot_download_fn=lambda **kwargs: str(snapshot),
            )
            destination = root / "destination"
            destination.mkdir()
            with self.assertRaisesRegex(
                HuggingFaceAssetError, "huggingface_snapshot_path_escape"
            ):
                downloader.download(
                    provider="huggingface",
                    repo_id="fixture/model",
                    revision=COMMIT,
                    destination=destination,
                    allow_patterns=("*.safetensors",),
                    token=None,
                )

    def test_training_resolution_rejects_tampered_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = _write_snapshot(root)
            info = SimpleNamespace(
                sha=COMMIT,
                siblings=[
                    SimpleNamespace(rfilename="config.json"),
                    SimpleNamespace(rfilename="model.safetensors"),
                ],
                card_data={"license": "mit"},
            )
            downloader = HuggingFaceHubDownloader(
                api_factory=lambda token: FakeApi(info, [], token),
                snapshot_download_fn=lambda **kwargs: str(snapshot),
            )
            store = ModelAssetStore(root / "assets")
            asset = download_huggingface_asset(
                store,
                repo_id="fixture/model",
                commit=COMMIT,
                downloader=downloader,
            )
            (store.asset_files_dir(asset.asset_id) / "config.json").write_text(
                '{"tampered":true}', encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ModelAssetError, "model_asset_integrity_verification_failed"
            ):
                resolve_training_asset(store, asset.asset_id)
            self.assertEqual(store.get(asset.asset_id).status, "quarantined")


if __name__ == "__main__":
    unittest.main()
