from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable, Iterable

from .model_assets import COMMIT_PATTERN, REPO_ID_PATTERN


class HuggingFaceCatalogError(ValueError):
    """A sanitized Hugging Face discovery or compatibility failure."""


@dataclass(frozen=True)
class HuggingFaceCatalog:
    """Read-only model discovery through the official Hugging Face client."""

    api_factory: Callable[..., Any] | None = None
    max_model_bytes: int = 256 * 1024 * 1024

    def _api(self, token: str | None = None) -> Any:
        if self.api_factory is not None:
            return self.api_factory(token=token)
        try:
            module = importlib.import_module("huggingface_hub")
            factory = getattr(module, "HfApi")
        except (ImportError, AttributeError) as exc:
            raise HuggingFaceCatalogError(
                "capability_unavailable:huggingface_hub"
            ) from exc
        return factory(token=token)

    def capability(self) -> dict[str, Any]:
        try:
            self._api()
        except HuggingFaceCatalogError as exc:
            return {
                "available": False,
                "provider": "huggingface",
                "reason": str(exc),
            }
        return {
            "available": True,
            "provider": "huggingface",
            "search": "official_hf_api",
            "download_policy": "explicit_approval_and_immutable_commit",
        }

    def search(
        self,
        query: str,
        *,
        pipeline_tag: str | None = None,
        limit: int = 10,
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        selected_query = query.strip()
        if not selected_query or len(selected_query) > 160:
            raise HuggingFaceCatalogError("invalid_huggingface_search_query")
        if not isinstance(limit, int) or not 1 <= limit <= 20:
            raise HuggingFaceCatalogError("invalid_huggingface_search_limit")
        try:
            models: Iterable[Any] = self._api(token).list_models(
                search=selected_query,
                pipeline_tag=pipeline_tag,
                sort="downloads",
                direction=-1,
                limit=limit,
                full=True,
                cardData=True,
                fetch_config=True,
                token=token,
            )
            return [self._summary(item) for item in models]
        except HuggingFaceCatalogError:
            raise
        except Exception:
            raise HuggingFaceCatalogError("huggingface_search_failed") from None

    def model_card(
        self,
        repo_id: str,
        *,
        revision: str | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        selected_repo = _repo_id(repo_id)
        if revision is not None and not COMMIT_PATTERN.fullmatch(revision.strip().lower()):
            raise HuggingFaceCatalogError("revision_not_immutable_commit")
        try:
            info = self._api(token).model_info(
                repo_id=selected_repo,
                revision=revision,
                files_metadata=True,
                token=token,
            )
            card = self._summary(info, include_files=True)
            resolved = str(getattr(info, "sha", "")).strip().lower()
            if not COMMIT_PATTERN.fullmatch(resolved):
                raise HuggingFaceCatalogError("huggingface_commit_unavailable")
            if revision is not None and resolved != revision.strip().lower():
                raise HuggingFaceCatalogError("resolved_commit_mismatch")
            card["revision"] = resolved
            card["compatibility"] = _compatibility(card, self.max_model_bytes)
            return card
        except HuggingFaceCatalogError:
            raise
        except Exception:
            raise HuggingFaceCatalogError("huggingface_model_card_failed") from None

    def _summary(self, info: Any, *, include_files: bool = False) -> dict[str, Any]:
        repo_id = _repo_id(str(getattr(info, "id", None) or getattr(info, "modelId", "")))
        card_data = getattr(info, "card_data", None) or getattr(info, "cardData", None)
        if hasattr(card_data, "to_dict"):
            card_data = card_data.to_dict()
        card_data = card_data if isinstance(card_data, dict) else {}
        tags = tuple(
            str(item) for item in (getattr(info, "tags", None) or ()) if isinstance(item, str)
        )
        result: dict[str, Any] = {
            "repository": repo_id,
            "revision": str(getattr(info, "sha", "") or "").strip().lower() or None,
            "license": _license(card_data),
            "library": str(getattr(info, "library_name", "") or "unknown"),
            "pipeline_tag": str(getattr(info, "pipeline_tag", "") or "unknown"),
            "tags": list(tags[:40]),
            "downloads": int(getattr(info, "downloads", 0) or 0),
            "likes": int(getattr(info, "likes", 0) or 0),
        }
        if include_files:
            files: list[dict[str, Any]] = []
            for sibling in getattr(info, "siblings", None) or ():
                raw = getattr(sibling, "rfilename", None)
                if raw is None and isinstance(sibling, dict):
                    raw = sibling.get("rfilename")
                path = _display_path(raw)
                if path is None:
                    continue
                size = getattr(sibling, "size", None)
                if size is None and isinstance(sibling, dict):
                    size = sibling.get("size")
                files.append(
                    {
                        "path": path,
                        "size_bytes": int(size) if isinstance(size, int) and size >= 0 else None,
                    }
                )
            result["files"] = sorted(files, key=lambda item: item["path"])
            result["total_size_bytes"] = sum(
                int(item["size_bytes"] or 0) for item in files
            )
        return result


def _repo_id(value: str) -> str:
    selected = value.strip()
    if not REPO_ID_PATTERN.fullmatch(selected) or any(
        part in {"", ".", ".."} for part in selected.split("/")
    ):
        raise HuggingFaceCatalogError("invalid_repo_id")
    return selected


def _display_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or len(value) > 512:
        return None
    return "/".join(part for part in path.parts if part not in {"", "."}) or None


def _license(card_data: dict[str, Any]) -> str:
    value = card_data.get("license")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (list, tuple)):
        selected = [str(item).strip() for item in value if str(item).strip()]
        if selected:
            return " AND ".join(selected)
    return "unknown"


def _runtime_available() -> bool:
    try:
        module = importlib.import_module("onnxruntime")
        providers = tuple(module.get_available_providers())
    except (ImportError, AttributeError):
        return False
    return "CPUExecutionProvider" in providers


def _compatibility(card: dict[str, Any], max_model_bytes: int) -> dict[str, Any]:
    files = card.get("files", [])
    paths = {str(item.get("path")) for item in files}
    onnx_files = [
        item for item in files if str(item.get("path", "")).lower().endswith(".onnx")
    ]
    onnx_bytes = sum(int(item.get("size_bytes") or 0) for item in onnx_files)
    checks = {
        "known_license": card.get("license") != "unknown",
        "onnx_payload": bool(onnx_files),
        "preprocess_config": "config.json" in paths,
        "local_cpu_runtime": _runtime_available(),
        "within_local_size_budget": 0 < onnx_bytes <= max_model_bytes,
        "image_classification_tag": card.get("pipeline_tag") == "image-classification"
        or "image-classification" in card.get("tags", []),
    }
    blocking = [name for name, passed in checks.items() if not passed]
    state = "compatible_candidate" if not blocking else "unsupported"
    if blocking == ["known_license"]:
        state = "needs_license_review"
    return {
        "state": state,
        "checks": checks,
        "blocking_reasons": blocking,
        "training_binding": "image_classification_onnx_feature_v1",
    }
