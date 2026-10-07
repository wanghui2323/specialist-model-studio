"""Immutable public Hub assets for isolated experiments; never imports code."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from .errors import ContractError, HarnessError
from .execution_workspace import digest, seal, verified
from .io_utils import sha256_file, write_json
from .model_sources import evaluate_license_policy, normalize_repository, normalize_source_path


class ExecutionAssetStore:
    def __init__(self, workspace: Any) -> None:
        self.workspace = workspace
        self.lock = RLock()

    def _root(self, task_id: str) -> Path:
        task = self.workspace._task_dir(task_id)
        if not self.workspace._task_path(task_id).is_file():
            raise FileNotFoundError("training task not found")
        root = task / "execution_assets"
        if root.is_symlink():
            raise ContractError("asset store is unsafe")
        return root

    def get(self, task_id: str, asset_id: str, *, private: bool = False) -> dict[str, Any]:
        if not re.fullmatch(r"asset-[a-f0-9]{24}", asset_id):
            raise FileNotFoundError("execution asset not found")
        root = self._root(task_id) / asset_id
        value = verified(root / "asset.json", "manifest_sha256")
        if value.get("task_id") != task_id or value.get("asset_id") != asset_id:
            raise ContractError("execution asset owner mismatch")
        for item in value["files"]:
            path = root / "files" / normalize_source_path(item["path"])
            if path.is_symlink() or not path.is_file() or root.resolve() not in path.resolve().parents or path.stat().st_size != item["bytes"] or (private and sha256_file(path) != item["sha256"]):
                raise ContractError("execution asset contents changed")
        return {**value, **({"root": str(root / "files")} if private else {})}

    def list(self, task_id: str) -> list[dict[str, Any]]:
        return [self.get(task_id, p.parent.name) for p in sorted(self._root(task_id).glob("asset-*/asset.json"))]

    def acquire(self, task_id: str, *, repository: str, revision: str,
                files: list[str], approval: dict[str, Any]) -> dict[str, Any]:
        from huggingface_hub import HfApi, hf_hub_download
        from .execution_workspace import approval_record
        granted = approval_record(approval)
        repo = normalize_repository(repository)
        if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{40}", revision):
            raise ContractError("execution assets require a full immutable Hub commit")
        if not isinstance(files, list) or not 1 <= len(files) <= 64:
            raise ContractError("execution assets require 1 to 64 explicit files")
        selected = sorted({normalize_source_path(p) for p in files})
        asset_id = "asset-" + digest({"task_id": task_id, "repository": repo, "revision": revision, "files": selected})[:24]
        with self.lock:
            root = self._root(task_id)
            target = root / asset_id
            if (target / "asset.json").is_file():
                return self.get(task_id, asset_id)
            info = HfApi().model_info(repo, revision=revision, files_metadata=True)
            if info.sha != revision or info.private or info.gated:
                raise ContractError("asset source must be the exact public, ungated commit")
            inventory = {p.rfilename: p for p in info.siblings}
            if not set(selected) <= set(inventory):
                raise ContractError("selected asset file is absent from the immutable source")
            total = sum(int(inventory[p].size or 0) for p in selected)
            if total > 1024**3 or any(inventory[p].size is None for p in selected):
                raise ContractError("asset download exceeds 1GiB or has unknown file sizes")
            license_name = str(getattr(info.card_data, "license", None) or "unknown")
            policy = evaluate_license_policy(license_name, "known" if license_name != "unknown" else "unknown")
            if policy["decision"] == "deny":
                raise ContractError("source license explicitly restricts this asset acquisition")
            # Unknown metadata is exposed for explicit local-use review, not
            # relabelled as a permissive license or published automatically.
            temporary = root / (".tmp-" + uuid4().hex)
            temporary.mkdir(parents=True, mode=0o700)
            rows = []
            try:
                for name in selected:
                    downloaded = Path(hf_hub_download(repo_id=repo, revision=revision, filename=name,
                                                     token=False, cache_dir=str(root / ".hub-cache")))
                    actual = sha256_file(downloaded)
                    declared = inventory[name].lfs.sha256 if inventory[name].lfs is not None else None
                    if declared and actual != declared:
                        raise ContractError("Hub asset SHA-256 does not match fixed source metadata")
                    size = downloaded.stat().st_size
                    if size != inventory[name].size:
                        raise ContractError("Hub asset size does not match fixed source metadata")
                    destination = temporary / "files" / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(downloaded, destination)
                    destination.chmod(0o444)
                    rows.append({"path": name, "sha256": actual, "bytes": size})
                record = seal({"schema_version": "0.1", "object_type": "ExecutionAsset", "task_id": task_id,
                               "asset_id": asset_id, "provider": "huggingface", "repository": repo, "resolved_commit": revision,
                               "files": rows, "license": license_name, "license_policy": policy,
                               "license_review_required": policy["decision"] != "allow", "approval": granted,
                               "source_size_bytes": total, "executable_imported_on_host": False}, "manifest_sha256")
                write_json(temporary / "asset.json", record)
                os.replace(temporary, target)
                return self.get(task_id, asset_id)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
