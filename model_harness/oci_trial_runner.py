"""Trusted stdin-only ONNX trial entrypoint; never import model code on the host.

The controller supplies an approved, verified asset and one opaque input. This
entrypoint is not a repository installer, qualification runner, or training Run.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys

MAX_PACKET_BYTES = 24 * 1024 * 1024
MAX_INPUT_BYTES = 4 * 1024 * 1024


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _container_guard() -> None:
    if sys.platform != "linux" or not Path("/.dockerenv").is_file():
        raise ValueError("linux_container_required")
    if os.getuid() != 65534 or os.getgid() != 65534:
        raise ValueError("unprivileged_container_required")
    if {p.name for p in Path("/sys/class/net").iterdir()} != {"lo"}:
        raise ValueError("offline_container_required")
    if any(os.environ.get(key) for key in (
        "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY", "MODEL_HARNESS_AGENT_BRIDGE_TOKEN",
    )):
        raise ValueError("ambient_credentials_rejected")


def validate_packet(raw: bytes) -> tuple[dict, dict[str, bytes]]:
    if not raw or len(raw) > MAX_PACKET_BYTES:
        raise ValueError("packet_size_limit")
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result
    packet = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(packet, dict) or packet.get("schema_version") != "1.0":
        raise ValueError("invalid_packet")
    for field in ("task_id", "trial_id"):
        if not isinstance(packet.get(field), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", packet[field]):
            raise ValueError("invalid_identity")
    for field in ("plan_sha256", "input_sha256"):
        if not isinstance(packet.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", packet[field]):
            raise ValueError("invalid_digest")
    asset = packet.get("asset")
    blobs = packet.get("blobs")
    if not isinstance(asset, dict) or not isinstance(blobs, dict) or set(blobs) != {"model.onnx", "config.json", "sample"}:
        raise ValueError("invalid_asset_packet")
    files = asset.get("files")
    if not isinstance(files, list) or any(not isinstance(item, dict) for item in files):
        raise ValueError("invalid_manifest")
    records = {item.get("relative_path"): item for item in files}
    if len(records) != len(files):
        raise ValueError("duplicate_asset_file")
    if not {"model.onnx", "config.json"} <= records.keys() or not records.keys() <= {"model.onnx", "config.json", "README.md"}:
        raise ValueError("unsupported_asset_file")
    for item in files:
        if type(item.get("size_bytes")) is not int or item["size_bytes"] <= 0 or not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("invalid_manifest_record")
    manifest = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if _hash(manifest) != asset.get("manifest_sha256"):
        raise ValueError("manifest_digest_mismatch")
    decoded = {}
    for name, text in blobs.items():
        if not isinstance(text, str):
            raise ValueError("invalid_blob")
        value = base64.b64decode(text, validate=True)
        limit = MAX_INPUT_BYTES if name == "sample" else (1024 * 1024 if name == "config.json" else 16 * 1024 * 1024)
        if not value or len(value) > limit:
            raise ValueError("blob_size_limit")
        if name == "sample":
            expected = packet["input_sha256"]
        else:
            record = records.get(name, {})
            if record.get("size_bytes") != len(value):
                raise ValueError("asset_size_mismatch")
            expected = record.get("sha256")
        if _hash(value) != expected:
            raise ValueError("blob_digest_mismatch")
        decoded[name] = value
    return packet, decoded


def main() -> int:
    try:
        # Guard before importing native image/model runtimes or reading input.
        _container_guard()
        packet, blobs = validate_packet(sys.stdin.buffer.read(MAX_PACKET_BYTES + 1))
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from model_harness.model_assets import ModelAsset
        from model_harness.huggingface_assets import TrainingModelAsset
        from model_harness.onnx_image_features import OnnxImageFeatureExtractor
        work = Path("/work")
        for name, value in blobs.items():
            with (work / name).open("xb") as target:
                target.write(value)
        asset = ModelAsset.from_dict(packet["asset"])
        handle = TrainingModelAsset(asset, work, tuple((name, work / name) for name in ("model.onnx", "config.json")))
        result = OnnxImageFeatureExtractor(handle, max_output_elements=4096).extract(work / "sample")
        output = {
            "schema_version": "1.0", "task_id": packet["task_id"],
            "trial_id": packet["trial_id"], "plan_sha256": packet["plan_sha256"],
            "status": "succeeded", "input_sha256": packet["input_sha256"],
            "model_sha256": result.provenance.model_sha256,
            "config_sha256": result.provenance.config_sha256,
            "provider": "CPUExecutionProvider", "features": result.features.tolist(),
            "classes": list(result.classes),
            "output_sha256": _hash(result.features.astype("<f4").tobytes()),
            "timing": result.to_dict(include_features=False)["timing"],
        }
        print(json.dumps(output, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as exc:
        # No local paths, sample bytes or untrusted exception text in evidence.
        print(json.dumps({"schema_version": "1.0", "status": "failed", "error_code": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
