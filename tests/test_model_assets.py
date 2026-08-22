from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from model_harness.io_utils import write_json
from model_harness.model_assets import (
    DownloadResult,
    ModelAsset,
    ModelAssetDownloader,
    ModelAssetError,
    ModelAssetStore,
)


COMMIT = "a" * 40


class FixtureDownloader:
    def __init__(
        self,
        files: dict[str, bytes],
        *,
        resolved_commit: str = COMMIT,
        license_name: str = "apache-2.0",
        executable: str | None = None,
        symlink: tuple[str, str] | None = None,
        escaped_file: tuple[str, bytes] | None = None,
    ) -> None:
        self.files = files
        self.resolved_commit = resolved_commit
        self.license_name = license_name
        self.executable = executable
        self.symlink = symlink
        self.escaped_file = escaped_file
        self.calls: list[dict[str, object]] = []

    def download(
        self,
        *,
        provider: str,
        repo_id: str,
        revision: str,
        destination: Path,
        allow_patterns: tuple[str, ...],
        token: str | None,
    ) -> DownloadResult:
        self.calls.append(
            {
                "provider": provider,
                "repo_id": repo_id,
                "revision": revision,
                "allow_patterns": allow_patterns,
                "token_seen": token is not None,
            }
        )
        for relative_path, payload in self.files.items():
            target = destination / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        if self.executable:
            os.chmod(destination / self.executable, 0o755)
        if self.symlink:
            link_name, target = self.symlink
            link = destination / link_name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
        if self.escaped_file:
            relative_path, payload = self.escaped_file
            (destination.parent / relative_path).write_bytes(payload)
        return DownloadResult(
            resolved_commit=self.resolved_commit, license=self.license_name
        )


class FailingDownloader:
    def download(self, **kwargs: object) -> DownloadResult:
        raise RuntimeError(f"remote rejected secret {kwargs.get('token')}")


def _valid_files() -> dict[str, bytes]:
    header = json.dumps(
        {"weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}},
        separators=(",", ":"),
    ).encode("utf-8")
    safetensors = len(header).to_bytes(8, "little") + header + struct.pack("<f", 1.0)
    return {
        "config.json": b'{"model_type":"fixture"}',
        "tokenizer/tokenizer.json": b'{"version":"1.0"}',
        "model.safetensors": safetensors,
        "README.md": b"# Local fixture\n",
        "LICENSE": b"Apache-2.0\n",
    }


def _disk_bytes(root: Path) -> bytes:
    payload = bytearray()
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            payload.extend(path.read_bytes())
    return bytes(payload)


class ModelAssetStoreTests(unittest.TestCase):
    def test_success_pins_commit_builds_manifest_and_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "model-assets"
            token = "hf_secret_must_never_reach_disk"
            store = ModelAssetStore(root, max_file_bytes=1024, max_total_bytes=4096)
            downloader = FixtureDownloader(_valid_files())
            self.assertIsInstance(downloader, ModelAssetDownloader)
            asset = store.download(
                provider="huggingface",
                repo_id="fixture/tiny-keyword-model",
                requested_revision=COMMIT,
                downloader=downloader,
                token=token,
            )
            self.assertEqual(asset.requested_revision, COMMIT)
            self.assertEqual(asset.resolved_commit, COMMIT)
            self.assertEqual(asset.license, "apache-2.0")
            self.assertEqual(asset.security_status, "verified")
            self.assertEqual(asset.status, "active")
            self.assertEqual(len(asset.manifest_sha256), 64)
            self.assertEqual(
                [item.relative_path for item in asset.files],
                [
                    "LICENSE",
                    "README.md",
                    "config.json",
                    "model.safetensors",
                    "tokenizer/tokenizer.json",
                ],
            )
            self.assertTrue(store.verify(asset.asset_id).ok)
            self.assertEqual(store.get(asset.asset_id), asset)
            self.assertEqual(store.list_assets(), [asset])
            self.assertNotIn(token.encode(), _disk_bytes(root))

            restarted = ModelAssetStore(root)
            self.assertEqual(restarted.get(asset.asset_id), asset)
            self.assertTrue(restarted.verify(asset.asset_id).ok)
            self.assertEqual(restarted.asset_files_dir(asset.asset_id).name, "files")
            self.assertNotIn(token.encode(), _disk_bytes(root))

    def test_non_commit_revision_is_quarantined_without_downloading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "model-assets"
            store = ModelAssetStore(root)
            downloader = FixtureDownloader(_valid_files())
            with self.assertRaisesRegex(
                ModelAssetError, "revision_not_immutable_commit"
            ):
                store.download(
                    provider="huggingface",
                    repo_id="fixture/model",
                    requested_revision="main",
                    downloader=downloader,
                )
            self.assertEqual(downloader.calls, [])
            [asset] = store.list_assets()
            self.assertEqual(asset.requested_revision, "main")
            self.assertEqual(asset.status, "quarantined")
            self.assertEqual(asset.security_status, "rejected")
            self.assertEqual(asset.failure_code, "revision_not_immutable_commit")
            self.assertEqual(asset.files, ())

    def test_malicious_files_and_staging_escape_are_quarantined(self) -> None:
        cases = {
            "renamed_pickle": FixtureDownloader(
                {
                    "config.json": b"{}",
                    "model.safetensors": b"\x80\x04malicious pickle",
                }
            ),
            "symlink": FixtureDownloader(
                _valid_files(), symlink=("linked.model", "model.safetensors")
            ),
            "executable": FixtureDownloader(
                _valid_files(), executable="model.safetensors"
            ),
            "path_escape": FixtureDownloader(
                _valid_files(), escaped_file=("escaped.json", b"{}")
            ),
            "pickle_extension": FixtureDownloader(
                {**_valid_files(), "weights.pkl": b"pickle"}
            ),
        }
        for name, downloader in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "model-assets"
                store = ModelAssetStore(root)
                with self.assertRaises(ModelAssetError):
                    store.download(
                        provider="huggingface",
                        repo_id="fixture/model",
                        requested_revision=COMMIT,
                        downloader=downloader,
                    )
                [asset] = store.list_assets()
                self.assertEqual(asset.status, "quarantined")
                self.assertEqual(asset.security_status, "rejected")
                quarantine = root / "quarantine" / asset.asset_id
                self.assertEqual(
                    [item.name for item in quarantine.iterdir()], ["asset.json"]
                )
                self.assertFalse((root / "staging" / "escaped.json").exists())

    def test_resolved_revision_must_equal_requested_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ModelAssetStore(Path(temporary) / "model-assets")
            downloader = FixtureDownloader(
                _valid_files(), resolved_commit="b" * 40
            )
            with self.assertRaisesRegex(ModelAssetError, "resolved_commit_mismatch"):
                store.download(
                    provider="huggingface",
                    repo_id="fixture/model",
                    requested_revision=COMMIT,
                    downloader=downloader,
                )
            [asset] = store.list_assets()
            self.assertEqual(asset.status, "quarantined")
            self.assertEqual(asset.resolved_commit, "")

    def test_downloader_error_cannot_persist_token_or_raw_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "model-assets"
            store = ModelAssetStore(root)
            token = "hf_exception_secret"
            with self.assertRaisesRegex(ModelAssetError, "downloader_failed") as raised:
                store.download(
                    provider="huggingface",
                    repo_id="fixture/model",
                    requested_revision=COMMIT,
                    downloader=FailingDownloader(),
                    token=token,
                )
            self.assertNotIn(token, str(raised.exception))
            self.assertNotIn(token.encode(), _disk_bytes(root))
            [asset] = store.list_assets()
            self.assertEqual(asset.failure_code, "downloader_failed")

    def test_downloader_cannot_smuggle_ephemeral_token_into_asset_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "model-assets"
            store = ModelAssetStore(root)
            token = "hf_never_activate_this_secret"
            downloader = FixtureDownloader(
                {
                    "config.json": b"{}",
                    "model.safetensors": b"prefix-" + token.encode() + b"-suffix",
                }
            )
            with self.assertRaisesRegex(
                ModelAssetError, "credential_material_detected"
            ):
                store.download(
                    provider="huggingface",
                    repo_id="fixture/model",
                    requested_revision=COMMIT,
                    downloader=downloader,
                    token=token,
                )
            self.assertNotIn(token.encode(), _disk_bytes(root))
            [asset] = store.list_assets()
            self.assertEqual(asset.status, "quarantined")
            self.assertEqual(asset.failure_code, "credential_material_detected")

    def test_authorization_material_is_rejected_without_explicit_token_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "model-assets"
            store = ModelAssetStore(root)
            downloader = FixtureDownloader(
                {
                    "config.json": b'{"authorization":"Bearer should-not-be-here"}',
                    "model.safetensors": _valid_files()["model.safetensors"],
                }
            )
            with self.assertRaisesRegex(
                ModelAssetError, "credential_material_detected"
            ):
                store.download(
                    provider="huggingface",
                    repo_id="fixture/model",
                    requested_revision=COMMIT,
                    downloader=downloader,
                )
            self.assertNotIn(b"should-not-be-here", _disk_bytes(root))

    def test_file_tamper_is_detected_and_active_asset_is_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "model-assets"
            store = ModelAssetStore(root)
            asset = store.download(
                provider="huggingface",
                repo_id="fixture/model",
                requested_revision=COMMIT,
                downloader=FixtureDownloader(_valid_files()),
            )
            model_path = store.asset_files_dir(asset.asset_id) / "model.safetensors"
            model_path.write_bytes(model_path.read_bytes() + b"tampered")
            verification = store.verify(asset.asset_id)
            self.assertFalse(verification.ok)
            self.assertIn("unsafe_or_unreadable_file_tree", verification.errors)
            self.assertEqual(verification.asset.status, "quarantined")
            self.assertEqual(verification.asset.security_status, "tampered")
            self.assertFalse((root / "active" / asset.asset_id).exists())
            self.assertTrue((root / "quarantine" / asset.asset_id).is_dir())
            self.assertEqual(store.get(asset.asset_id), verification.asset)
            self.assertFalse(store.verify(asset.asset_id).ok)

    def test_restart_recovers_interrupted_staging_without_preserving_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "model-assets"
            store = ModelAssetStore(root)
            asset = ModelAsset(
                asset_id="asset-123456789abc",
                provider="huggingface",
                repo_id="fixture/model",
                requested_revision=COMMIT,
                resolved_commit="",
                license="unknown",
                security_status="pending",
                allow_patterns=("*.safetensors",),
                files=(),
                manifest_sha256=(
                    "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e9c6f7b0df31e40f4d2f6f2"
                ),
                status="staging",
                created_at="2026-08-22T00:00:00+00:00",
            )
            container = store.staging_dir / asset.asset_id
            (container / "files").mkdir(parents=True)
            secret = b"hf_interrupted_secret"
            (container / "files" / "model.safetensors").write_bytes(secret)
            write_json(container / "asset.json", asset.to_dict())

            restarted = ModelAssetStore(root)
            recovered = restarted.get(asset.asset_id)
            self.assertEqual(recovered.status, "quarantined")
            self.assertEqual(recovered.security_status, "rejected")
            self.assertEqual(recovered.failure_code, "interrupted_during_staging")
            self.assertNotIn(secret, _disk_bytes(root))
            self.assertFalse((root / "staging" / asset.asset_id).exists())


if __name__ == "__main__":
    unittest.main()
