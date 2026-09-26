#!/usr/bin/env python3
"""Container-only, fixed-model CPU inference smoke test; never creates a Run.

Prepare in an approved network-enabled, non-root container, then invoke infer
in a new non-root container with --network=none and the same private /probe
volume (or its frozen /tmp/probe image copy). The caller owns image provenance, mount restrictions, cgroup limits,
and external timeout/cancellation. This script does not manage containers.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import sys
import tempfile
from datetime import UTC, datetime
from typing import Any


REPO_ID = "pyronear/mobilenet_v3_small"
COMMIT = "a6a0b39ca1f5b0a247eb0a2e83f06cd95fc03674"
MODEL_SHA256 = "8fd451f919499e30e879eda19bfd2b249ceec77e4f1c02f7b022730e365ae897"
MODEL_BYTES = 6_068_953
EXPECTED_LICENSE = "apache-2.0"
FILES = ("README.md", "config.json", "model.onnx")
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
RTOL = 1e-6
ATOL = 1e-7
SCOPE = "fixed_external_model_cpu_inference_smoke"
MANIFEST_NAME = "prepared-model.json"
SAMPLE_NAME = "public-synthetic-sample.png"


class ProbeError(RuntimeError):
    pass


class ProbeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ProbeError(f"invalid_arguments: {message}")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ProbeError(reason)


def _boundary(command: str, workspace: str) -> tuple[Path, dict[str, Any]]:
    _require(sys.platform == "linux", "linux_container_required")
    marker = Path("/.dockerenv")
    _require(marker.is_file() and not marker.is_symlink(), "docker_container_marker_required")
    _require(os.getuid() != 0 and os.geteuid() != 0, "non_root_user_required")
    root = Path(workspace)
    _require(root in {Path("/probe"), Path("/tmp/probe")}, "workspace_must_be_container_private_probe")
    _require(not root.is_symlink() and root.resolve() == root, "unsafe_workspace_path")
    _require(root.is_dir(), "caller_must_provision_probe_directory")
    interfaces = sorted(path.name for path in Path("/sys/class/net").iterdir())
    if command == "infer":
        _require(interfaces == ["lo"], "inference_requires_only_loopback_network")
    _require(
        not any(os.environ.get(key) for key in (
            "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_HUB_TOKEN",
        )),
        "credential_environment_not_allowed",
    )
    _require(
        os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
        == "https://huggingface.co",
        "only_official_public_huggingface_endpoint_allowed",
    )
    # Set before importing huggingface_hub (its constants are initialized once).
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["ORT_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1" if command == "infer" else "0"
    return root, {
        "platform": sys.platform,
        "architecture": platform.machine(),
        "uid": os.getuid(),
        "euid": os.geteuid(),
        "dockerenv_present": True,
        "network_interfaces": interfaces,
        "offline_execution": command == "infer",
        "implicit_hf_token_disabled": True,
        "note": "These checks do not independently certify mounts, cgroups, or the runtime isolation policy.",
    }


def _safe_child(root: Path, name: str, *, required: bool = False) -> Path:
    path = root / name
    _require(path.parent == root and not path.is_symlink(), "unsafe_probe_child_path")
    _require(path.resolve() == path, "probe_child_path_escape")
    if required:
        _require(path.is_file(), "required_probe_file_missing")
    return path


def _public_sample() -> bytes:
    # Same trusted synthetic image as run_hf_real_scenario._new_sample_image;
    # do not import that script, which also imports the HTTP/server stack.
    from PIL import Image, ImageDraw

    output = io.BytesIO()
    image = Image.new("RGB", (53, 41), (215, 48, 35))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 7, 32, 33), outline="white", width=3)
    draw.line((3, 37, 48, 37), fill=(30, 210, 95), width=2)
    image.save(output, format="PNG")
    return output.getvalue()


def _store(root: Path, *, readonly: bool = False) -> Any:
    from model_harness.model_assets import ModelAssetStore

    assets_root = _safe_child(root, "assets")
    if readonly:
        _require(assets_root.is_dir(), "prepared_asset_store_missing")
        for name in ("active", "staging", "quarantine"):
            directory = assets_root / name
            _require(directory.is_dir() and not directory.is_symlink(), "prepared_asset_directory_invalid")
        _require(not any((assets_root / "staging").iterdir()), "read_only_infer_requires_no_staged_assets")
    return ModelAssetStore(
        assets_root, max_file_bytes=MAX_FILE_BYTES,
        max_total_bytes=MAX_TOTAL_BYTES, max_files=len(FILES),
    )


def _check_asset(asset: Any, store: Any) -> Any:
    from model_harness.huggingface_assets import resolve_training_asset

    _require(asset.provider == "huggingface" and asset.repo_id == REPO_ID, "unexpected_model_source")
    _require(asset.requested_revision == COMMIT and asset.resolved_commit == COMMIT, "unexpected_model_commit")
    _require(asset.status == "active" and asset.security_status == "verified", "model_asset_not_active_and_verified")
    _require(asset.license.strip().lower() == EXPECTED_LICENSE, "unexpected_model_license")
    _require({item.relative_path for item in asset.files} == set(FILES), "unexpected_asset_file_set")
    # Detect corruption before ModelAssetStore.verify(), whose normal failure
    # path quarantines assets. Inference must not mutate its frozen asset image.
    files_root = store.asset_files_dir(asset.asset_id)
    _require(not files_root.is_symlink(), "unsafe_asset_files_directory")
    _require({path.name for path in files_root.iterdir()} == set(FILES), "unexpected_materialized_file_set")
    for item in asset.files:
        path = files_root / item.relative_path
        _require(path.is_file() and not path.is_symlink(), "unsafe_materialized_asset_file")
        _require(path.stat().st_size == item.size_bytes, "materialized_asset_size_mismatch")
        _require(_file_sha256(path) == item.sha256, "materialized_asset_digest_mismatch")
    model = files_root / "model.onnx"
    _require(model.stat().st_size == MODEL_BYTES, "fixed_model_size_mismatch")
    _require(_file_sha256(model) == MODEL_SHA256, "fixed_model_sha256_mismatch")
    return resolve_training_asset(store, asset.asset_id, required_files=FILES)


def _anonymous_downloader() -> Any:
    from huggingface_hub import HfApi, snapshot_download
    from model_harness.huggingface_assets import HuggingFaceHubDownloader

    class AnonymousApi:
        def __init__(self, **_kwargs: Any) -> None:
            self.api = HfApi(token=False)

        def model_info(self, **kwargs: Any) -> Any:
            kwargs["token"] = False
            info = self.api.model_info(**kwargs)
            selected: dict[str, Any] = {}
            for item in info.siblings or ():
                name = str(item.rfilename)
                if name in FILES:
                    selected[name] = item
            _require(set(selected) == set(FILES), "required_fixed_model_files_missing")
            sizes = [getattr(selected[name], "size", None) for name in FILES]
            _require(
                all(isinstance(size, int) and 0 < size <= MAX_FILE_BYTES for size in sizes),
                "model_metadata_size_missing_or_over_budget",
            )
            _require(sum(sizes) <= MAX_TOTAL_BYTES, "model_metadata_total_over_budget")
            _require(getattr(selected["model.onnx"], "size", None) == MODEL_BYTES, "fixed_model_metadata_size_mismatch")
            return info

    def anonymous_snapshot(**kwargs: Any) -> str:
        kwargs["token"] = False
        return snapshot_download(**kwargs)

    # The existing downloader's public token type is str|None and rejects
    # False. Keep its public validation unchanged, but force token=False at
    # all official client calls through its supported dependency-injection API.
    return HuggingFaceHubDownloader(
        api_factory=AnonymousApi, snapshot_download_fn=anonymous_snapshot,
    )


def _common(command: str, boundary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "0.1", "command": command, "validation_scope": SCOPE,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "boundary": boundary, "probe_script_sha256": _file_sha256(Path(__file__)),
        "training_run_created": False, "release_gates_modified": False,
        "business_quality_accepted": False, "product_dynamic_execution_validated": False,
    }


def prepare(root: Path, boundary: dict[str, Any]) -> dict[str, Any]:
    from model_harness.huggingface_assets import download_huggingface_asset

    manifest_path = _safe_child(root, MANIFEST_NAME)
    sample_path = _safe_child(root, SAMPLE_NAME)
    _require(not manifest_path.exists(), "prepared_manifest_already_exists_use_infer")
    _require(not sample_path.exists(), "probe_sample_already_exists")
    store = _store(root)
    with tempfile.TemporaryDirectory(prefix="hf-public-", dir=root) as hf_home:
        os.environ["HF_HOME"] = hf_home
        os.environ["HF_HUB_CACHE"] = str(Path(hf_home) / "hub")
        os.environ["HF_TOKEN_PATH"] = str(Path(hf_home) / "unused-token")
        asset = download_huggingface_asset(
            store, repo_id=REPO_ID, commit=COMMIT, allow_patterns=FILES,
            token=None, downloader=_anonymous_downloader(),
        )
    _check_asset(asset, store)
    sample = _public_sample()
    with sample_path.open("xb") as stream:
        stream.write(sample)
    manifest = {
        "schema_version": "0.1", "validation_scope": SCOPE,
        "provider": "huggingface", "repo_id": REPO_ID, "commit": COMMIT,
        "asset_id": asset.asset_id, "asset_manifest_sha256": asset.manifest_sha256,
        "license": asset.license, "files": [item.to_dict() for item in asset.files],
        "fixed_model_sha256": MODEL_SHA256, "fixed_model_bytes": MODEL_BYTES,
        "sample_name": SAMPLE_NAME, "sample_sha256": _sha256(sample),
    }
    manifest["record_sha256"] = _sha256(_canonical(manifest))
    with manifest_path.open("xb") as stream:
        stream.write(_canonical(manifest) + b"\n")
    return {
        **_common("prepare", boundary), "status": "prepared", "manifest": manifest,
        "prepared_manifest_file_sha256": _file_sha256(manifest_path),
        "note": "Weights and public synthetic input are materialized; no model inference or training was executed.",
    }


def _allclose(left: list[float], right: list[float]) -> bool:
    return len(left) == len(right) and all(
        math.isfinite(a) and math.isfinite(b) and abs(a - b) <= ATOL + RTOL * abs(b)
        for a, b in zip(left, right)
    )


def infer(root: Path, boundary: dict[str, Any]) -> dict[str, Any]:
    import resource
    from model_harness.onnx_image_features import OnnxImageFeatureExtractor

    manifest_path = _safe_child(root, MANIFEST_NAME, required=True)
    _require(manifest_path.stat().st_size <= 64 * 1024, "prepared_manifest_too_large")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _require(isinstance(manifest, dict), "invalid_prepared_manifest")
    record_digest = manifest.get("record_sha256")
    unsigned = {key: value for key, value in manifest.items() if key != "record_sha256"}
    _require(record_digest == _sha256(_canonical(unsigned)), "prepared_manifest_digest_mismatch")
    expected = {
        "schema_version": "0.1", "validation_scope": SCOPE, "provider": "huggingface",
        "repo_id": REPO_ID, "commit": COMMIT, "license": EXPECTED_LICENSE,
        "fixed_model_sha256": MODEL_SHA256, "fixed_model_bytes": MODEL_BYTES,
        "sample_name": SAMPLE_NAME,
    }
    _require(all(manifest.get(key) == value for key, value in expected.items()), "prepared_manifest_source_mismatch")
    asset_id = manifest.get("asset_id")
    _require(isinstance(asset_id, str), "prepared_asset_id_missing")
    store = _store(root, readonly=True)
    asset = store.get(asset_id)
    _require(asset.manifest_sha256 == manifest.get("asset_manifest_sha256"), "original_asset_manifest_mismatch")
    _require([item.to_dict() for item in asset.files] == manifest.get("files"), "original_asset_file_records_mismatch")
    handle = _check_asset(asset, store)
    sample_path = _safe_child(root, SAMPLE_NAME, required=True)
    sample_hash = _file_sha256(sample_path)
    _require(sample_hash == manifest.get("sample_sha256"), "probe_sample_digest_mismatch")
    _require(sample_hash == _sha256(_public_sample()), "only_fixed_public_synthetic_sample_allowed")

    first = OnnxImageFeatureExtractor(handle)
    results = [first.extract(sample_path), first.extract(sample_path)]
    reloaded = OnnxImageFeatureExtractor(_check_asset(store.get(asset_id), store))
    results.append(reloaded.extract(sample_path))
    vectors = [result.features.tolist() for result in results]
    shapes = [list(result.features.shape) for result in results]
    _require(bool(vectors[0]) and all(shape == shapes[0] for shape in shapes), "inference_output_shape_mismatch")
    _require(all(all(math.isfinite(value) for value in vector) for vector in vectors), "inference_output_not_finite")
    _require(_allclose(vectors[0], vectors[1]) and _allclose(vectors[0], vectors[2]), "repeated_or_reloaded_inference_mismatch")
    _require(_file_sha256(sample_path) == sample_hash, "probe_sample_changed_during_execution")
    _, ending_boundary = _boundary("infer", str(root))
    records = []
    for index, result in enumerate(results):
        records.append({
            "execution_index": index + 1, "extractor_instance": 2 if index == 2 else 1,
            **result.to_dict(), "output_shape": shapes[index],
            "output_dtype": str(result.features.dtype),
            "output_sha256": _sha256(result.features.tobytes(order="C")),
            "output_hash_encoding": "C-order raw feature tensor bytes with recorded shape and dtype",
        })
    return {
        **_common("infer", ending_boundary), "status": "passed",
        "asset_id": asset_id, "repo_id": REPO_ID, "commit": COMMIT,
        "prepared_manifest_file_sha256": _file_sha256(manifest_path),
        "input": {"name": SAMPLE_NAME, "sha256": sample_hash, "kind": "public_synthetic_image"},
        "extractors": [first.describe(), reloaded.describe()], "executions": records,
        "checks": {"same_shape": True, "finite_outputs": True, "repeat_allclose": True,
                   "reload_allclose": True, "rtol": RTOL, "atol": ATOL},
        "process_resource": {
            "maximum_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
            "rss_note": "Linux getrusage(RUSAGE_SELF).ru_maxrss in KiB, converted to bytes; includes Python and runtime initialization.",
        },
        "note": "Real fixed-model CPU inference and reload only. The synthetic image has no semantic ground truth; this is not business quality acceptance, training, or Studio dynamic execution qualification.",
    }


def main(argv: list[str] | None = None) -> int:
    command: str | None = None
    try:
        parser = ProbeArgumentParser(description=__doc__)
        subcommands = parser.add_subparsers(dest="command", required=True)
        for name in ("prepare", "infer"):
            subparser = subcommands.add_parser(name)
            subparser.add_argument("--workspace", default="/probe")
        args = parser.parse_args(argv)
        command = args.command
        root, boundary = _boundary(command, args.workspace)
        # Permit execution from a minimal source copy, not an installed app.
        source_root = str(Path(__file__).resolve().parents[1])
        if source_root not in sys.path:
            sys.path.insert(0, source_root)
        report = prepare(root, boundary) if command == "prepare" else infer(root, boundary)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except Exception as error:
        report = {
            "schema_version": "0.1", "status": "failure", "command": command,
            "validation_scope": SCOPE, "error_type": type(error).__name__,
            "reason": str(error)[:500] if isinstance(error, ProbeError) else "dependency_or_execution_failed",
            "training_run_created": False, "release_gates_modified": False,
            "business_quality_accepted": False, "product_dynamic_execution_validated": False,
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
