from __future__ import annotations

import base64
import binascii
import json
import socket
import ssl
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    OpenerDirector,
    Request,
    build_opener,
)

import certifi

from .model_assets import COMMIT_PATTERN
from .model_sources import (
    MAX_DOCUMENT_BYTES,
    MAX_PROVIDER_RESPONSE_BYTES,
    MAX_TREE_FILES,
    ModelSourceIncompleteError,
    ModelSourceUpstreamError,
    ModelSourceValidationError,
    RemoteSourceFile,
    ResolvedSource,
    SourceDocument,
    is_analysis_document_path,
    normalize_commit,
    normalize_repository,
    normalize_revision,
    normalize_source_path,
    source_candidate_id,
    validate_ephemeral_token,
)


GITHUB_API_ORIGIN = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


class GitHubSourceNotFound(ModelSourceUpstreamError):
    """The selected GitHub repository, revision, or object is unavailable."""


class GitHubJsonTransport(Protocol):
    def request_json(
        self,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        token: str | None = None,
        max_bytes: int = MAX_PROVIDER_RESPONSE_BYTES,
    ) -> Any: ...


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class GitHubRestTransport:
    """Small, injectable GitHub REST client with a fixed API origin."""

    def __init__(
        self,
        *,
        opener: OpenerDirector | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise ValueError("GitHub timeout must be between 0 and 60 seconds")
        self._opener = opener or build_opener(
            _RejectRedirects(),
            HTTPSHandler(
                context=ssl.create_default_context(cafile=certifi.where())
            ),
        )
        self.timeout_seconds = float(timeout_seconds)

    def request_json(
        self,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        token: str | None = None,
        max_bytes: int = MAX_PROVIDER_RESPONSE_BYTES,
    ) -> Any:
        if (
            not isinstance(path, str)
            or not (path.startswith("/repos/") or path == "/search/repositories")
            or path.startswith("//")
            or "://" in path
            or "?" in path
            or "#" in path
            or "\\" in path
            or ".." in path.split("/")
        ):
            raise ModelSourceValidationError("unsafe_github_api_path")
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or max_bytes < 1
            or max_bytes > MAX_PROVIDER_RESPONSE_BYTES
        ):
            raise ModelSourceValidationError("invalid_github_response_limit")
        selected_token = validate_ephemeral_token(token)
        selected_query: dict[str, str] = {}
        for key, value in (query or {}).items():
            selected_key = str(key)
            selected_value = str(value)
            if (
                not selected_key
                or len(selected_key) > 80
                or len(selected_value) > 400
                or any(
                    ord(character) < 32 for character in selected_key + selected_value
                )
            ):
                raise ModelSourceValidationError("invalid_github_api_query")
            selected_query[selected_key] = selected_value
        url = f"{GITHUB_API_ORIGIN}{path}"
        if selected_query:
            url = f"{url}?{urlencode(selected_query)}"
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.github.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
        ):
            raise ModelSourceValidationError("unsafe_github_api_origin")
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "specialist-model-studio/0.9",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        if selected_token is not None:
            headers["Authorization"] = f"Bearer {selected_token}"
        request = Request(url, headers=headers, method="GET")
        try:
            response = self._opener.open(request, timeout=self.timeout_seconds)
            with response:
                status = int(response.getcode())
                if status != 200:
                    raise ModelSourceUpstreamError("github_unexpected_status")
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except (TypeError, ValueError) as exc:
                        raise ModelSourceUpstreamError(
                            "github_invalid_content_length"
                        ) from exc
                    if declared_length < 0 or declared_length > max_bytes:
                        raise ModelSourceUpstreamError(
                            "github_response_size_limit_exceeded"
                        )
                body = response.read(max_bytes + 1)
        except HTTPError as exc:
            if exc.code == 404:
                raise GitHubSourceNotFound("github_source_not_found") from None
            if exc.code == 401:
                raise ModelSourceUpstreamError("github_authentication_failed") from None
            if exc.code == 429 or (
                exc.code == 403
                and str(exc.headers.get("X-RateLimit-Remaining", "")) == "0"
            ):
                raise ModelSourceUpstreamError("github_rate_limited") from None
            if exc.code == 422 and "/commits/" in path:
                raise GitHubSourceNotFound(
                    "github_revision_not_found_or_invalid"
                ) from None
            if exc.code == 422 and path == "/search/repositories":
                raise ModelSourceValidationError(
                    "github_search_query_rejected"
                ) from None
            if 300 <= exc.code < 400:
                raise ModelSourceUpstreamError("github_redirect_rejected") from None
            raise ModelSourceUpstreamError("github_api_request_failed") from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            raise ModelSourceUpstreamError("github_api_request_failed") from None
        if len(body) > max_bytes:
            raise ModelSourceUpstreamError("github_response_size_limit_exceeded")
        if selected_token is not None and selected_token.encode("utf-8") in body:
            raise ModelSourceUpstreamError("github_response_contains_token")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ModelSourceUpstreamError("github_invalid_json_response") from None


@dataclass(frozen=True)
class GitHubSourceProvider:
    transport: GitHubJsonTransport = field(default_factory=GitHubRestTransport)
    provider_id: str = "github"

    def search(
        self,
        query: str,
        *,
        limit: int = 6,
        token: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        selected_query = str(query).strip()
        if (
            not selected_query
            or len(selected_query) > 160
            or any(ord(character) < 32 for character in selected_query)
        ):
            raise ModelSourceValidationError("invalid_github_search_query")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
            raise ModelSourceValidationError("invalid_github_search_limit")
        selected_token = validate_ephemeral_token(token)
        payload = self.transport.request_json(
            "/search/repositories",
            query={
                "q": selected_query,
                "sort": "stars",
                "order": "desc",
                "per_page": str(limit),
            },
            token=selected_token,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ModelSourceUpstreamError("github_invalid_search_response")
        candidates: list[dict[str, Any]] = []
        for item in payload["items"][:limit]:
            if not isinstance(item, dict):
                raise ModelSourceUpstreamError("github_invalid_search_item")
            try:
                repository = normalize_repository(str(item["full_name"]))
                requested_revision = normalize_revision(
                    str(item.get("default_branch") or "main")
                )
            except (KeyError, ModelSourceValidationError):
                raise ModelSourceUpstreamError("github_invalid_search_item") from None
            license_payload = item.get("license")
            license_name = "unknown"
            if isinstance(license_payload, dict):
                spdx = str(license_payload.get("spdx_id") or "").strip()
                if (
                    spdx
                    and spdx.lower() not in {"noassertion", "other", "unknown"}
                    and len(spdx) <= 200
                    and not any(ord(character) < 32 for character in spdx)
                ):
                    license_name = spdx
            description_value = item.get("description")
            description = (
                str(description_value).strip()[:320]
                if isinstance(description_value, str)
                else ""
            )
            stars = item.get("stargazers_count", 0)
            size_kib = item.get("size")
            if isinstance(stars, bool) or not isinstance(stars, int) or stars < 0:
                stars = 0
            if isinstance(size_kib, bool) or not isinstance(size_kib, int) or size_kib < 0:
                size_kib = None
            candidates.append(
                {
                    "candidate_id": source_candidate_id(
                        self.provider_id, repository, requested_revision
                    ),
                    "provider": self.provider_id,
                    "repository": repository,
                    "source_uri": f"https://github.com/{repository}",
                    "requested_revision": requested_revision,
                    "resolved_commit": None,
                    "license": license_name,
                    "license_status": "known" if license_name != "unknown" else "unknown",
                    "description": description,
                    "task_tag": "repository-search",
                    "popularity": {"stars": stars},
                    "repository_size_bytes": (
                        size_kib * 1024 if size_kib is not None else None
                    ),
                    "catalog_evidence": "github_official_search_api",
                }
            )
        return tuple(candidates)

    def resolve(
        self,
        repository: str,
        requested_revision: str | None,
        *,
        token: str | None = None,
    ) -> ResolvedSource:
        selected_repo = normalize_repository(repository)
        selected_revision = normalize_revision(requested_revision)
        selected_token = validate_ephemeral_token(token)
        owner, repo = selected_repo.split("/", 1)
        encoded_revision = quote(selected_revision, safe="")
        payload = self.transport.request_json(
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/commits/{encoded_revision}",
            token=selected_token,
        )
        if not isinstance(payload, dict):
            raise ModelSourceUpstreamError("github_invalid_commit_response")
        try:
            resolved_commit = normalize_commit(str(payload["sha"]))
            tree_reference = normalize_commit(str(payload["commit"]["tree"]["sha"]))
        except (KeyError, TypeError, ModelSourceValidationError):
            raise ModelSourceUpstreamError("github_invalid_commit_response") from None
        if (
            COMMIT_PATTERN.fullmatch(selected_revision.lower())
            and resolved_commit != selected_revision.lower()
        ):
            raise ModelSourceUpstreamError("resolved_commit_mismatch")

        license_name = "unknown"
        license_status = "unknown"
        try:
            license_payload = self.transport.request_json(
                f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/license",
                query={"ref": resolved_commit},
                token=selected_token,
            )
        except GitHubSourceNotFound:
            license_payload = None
        if isinstance(license_payload, dict):
            license_value = license_payload.get("license")
            if isinstance(license_value, dict):
                spdx = str(license_value.get("spdx_id", "")).strip()
                if (
                    spdx
                    and spdx.lower() not in {"noassertion", "other", "unknown"}
                    and len(spdx) <= 200
                    and not any(ord(character) < 32 for character in spdx)
                ):
                    license_name = spdx
                    license_status = "known"
        return ResolvedSource(
            provider=self.provider_id,
            repository=selected_repo,
            requested_revision=selected_revision,
            resolved_commit=resolved_commit,
            license=license_name,
            license_status=license_status,
            tree_reference=tree_reference,
            metadata={"source_kind": "github_repository"},
        )

    def list_tree(
        self,
        source: ResolvedSource,
        *,
        token: str | None = None,
    ) -> tuple[RemoteSourceFile, ...]:
        self._validate_source(source)
        selected_token = validate_ephemeral_token(token)
        owner, repo = source.repository.split("/", 1)
        tree_reference = source.tree_reference
        if tree_reference is None:
            raise ModelSourceValidationError("github_tree_reference_missing")
        payload = self.transport.request_json(
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/git/trees/{tree_reference}",
            query={"recursive": "1"},
            token=selected_token,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("tree"), list):
            raise ModelSourceUpstreamError("github_invalid_tree_response")
        if payload.get("truncated") is not False:
            raise ModelSourceIncompleteError("github_tree_truncated")
        try:
            returned_tree = normalize_commit(str(payload["sha"]))
        except (KeyError, ModelSourceValidationError):
            raise ModelSourceUpstreamError("github_invalid_tree_response") from None
        if returned_tree != tree_reference:
            raise ModelSourceUpstreamError("github_tree_reference_mismatch")
        raw_tree = payload["tree"]
        if len(raw_tree) > MAX_TREE_FILES:
            raise ModelSourceValidationError("source_tree_file_limit_exceeded")
        files: list[RemoteSourceFile] = []
        seen_paths: set[str] = set()
        for raw in raw_tree:
            if not isinstance(raw, dict):
                raise ModelSourceUpstreamError("github_invalid_tree_entry")
            try:
                path = normalize_source_path(str(raw["path"]))
                mode = str(raw["mode"])
                object_type = str(raw["type"])
                digest = normalize_commit(str(raw["sha"]))
            except (KeyError, ModelSourceValidationError):
                raise ModelSourceUpstreamError("github_invalid_tree_entry") from None
            if path in seen_paths:
                raise ModelSourceUpstreamError("github_duplicate_tree_path")
            seen_paths.add(path)
            if mode == "040000" and object_type == "tree":
                kind = "tree"
            elif mode == "100644" and object_type == "blob":
                kind = "blob"
            elif mode == "100755" and object_type == "blob":
                kind = "executable"
            elif mode == "120000" and object_type == "blob":
                kind = "symlink"
            elif mode == "160000" and object_type == "commit":
                kind = "submodule"
            else:
                raise ModelSourceUpstreamError("github_invalid_tree_entry")
            size_value = raw.get("size")
            if size_value is None:
                size = None
            elif (
                isinstance(size_value, bool)
                or not isinstance(size_value, int)
                or size_value < 0
            ):
                raise ModelSourceUpstreamError("github_invalid_tree_entry")
            else:
                size = size_value
            if kind in {"blob", "executable", "symlink"} and size is None:
                raise ModelSourceUpstreamError("github_invalid_tree_entry")
            files.append(
                RemoteSourceFile(
                    path=path,
                    kind=kind,
                    mode=mode,
                    size_bytes=size,
                    remote_digest=digest,
                )
            )
        return tuple(sorted(files, key=lambda item: item.path))

    def read_document(
        self,
        source: ResolvedSource,
        file: RemoteSourceFile,
        *,
        token: str | None = None,
    ) -> SourceDocument:
        self._validate_source(source)
        selected_token = validate_ephemeral_token(token)
        if (
            file.kind != "blob"
            or file.mode != "100644"
            or file.lfs_sha256 is not None
            or file.size_bytes is None
            or file.size_bytes > MAX_DOCUMENT_BYTES
            or not is_analysis_document_path(file.path)
        ):
            raise ModelSourceValidationError("github_document_not_readable")
        owner, repo = source.repository.split("/", 1)
        payload = self.transport.request_json(
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/git/blobs/{file.remote_digest}",
            token=selected_token,
            max_bytes=min(MAX_PROVIDER_RESPONSE_BYTES, MAX_DOCUMENT_BYTES * 2),
        )
        if not isinstance(payload, dict):
            raise ModelSourceUpstreamError("github_invalid_blob_response")
        if str(payload.get("sha", "")).lower() != file.remote_digest:
            raise ModelSourceUpstreamError("github_blob_digest_mismatch")
        if payload.get("encoding") != "base64" or not isinstance(
            payload.get("content"), str
        ):
            raise ModelSourceUpstreamError("github_invalid_blob_response")
        declared_size = payload.get("size")
        if (
            isinstance(declared_size, bool)
            or not isinstance(declared_size, int)
            or declared_size != file.size_bytes
        ):
            raise ModelSourceUpstreamError("github_blob_size_mismatch")
        try:
            encoded = b"".join(payload["content"].encode("ascii").split())
            content = base64.b64decode(encoded, validate=True)
        except (UnicodeEncodeError, binascii.Error):
            raise ModelSourceUpstreamError("github_invalid_blob_encoding") from None
        if len(content) != declared_size or len(content) > MAX_DOCUMENT_BYTES:
            raise ModelSourceUpstreamError("github_blob_size_mismatch")
        if content.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
            raise ModelSourceIncompleteError(
                "github_lfs_pointer_requires_object_metadata"
            )
        if selected_token is not None and selected_token.encode("utf-8") in content:
            raise ModelSourceValidationError("credential_material_detected")
        return SourceDocument.from_bytes(file.path, content)

    def _validate_source(self, source: ResolvedSource) -> None:
        if (
            not isinstance(source, ResolvedSource)
            or source.provider != self.provider_id
        ):
            raise ModelSourceValidationError("source_provider_mismatch")
        normalize_repository(source.repository)
        normalize_commit(source.resolved_commit)
