#!/usr/bin/env python3
"""Fail-closed helpers for v0.7 acceptance evidence.

The external evidence producer is intentionally untrusted for verdicts.  This
module gives the verifier a small, dependency-free JSON Schema subset and safe
artifact readers so it can validate and recompute every persisted observation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
from datetime import datetime
from pathlib import Path
from typing import Any


class SchemaValidationError(ValueError):
    """Raised when a JSON value violates the checked schema."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_equal(left: Any, right: Any) -> bool:
    # JSON Schema treats 1 and True as different JSON types.
    if type(left) is not type(right):
        return False
    return left == right


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def _resolve_pointer(root: dict[str, Any], pointer: str) -> dict[str, Any]:
    if pointer == "#":
        return root
    if not pointer.startswith("#/"):
        raise SchemaValidationError(f"unsupported non-local $ref: {pointer}")
    selected: Any = root
    for raw_part in pointer[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(selected, dict) or part not in selected:
            raise SchemaValidationError(f"unresolved $ref: {pointer}")
        selected = selected[part]
    if not isinstance(selected, dict):
        raise SchemaValidationError(f"$ref does not select a schema: {pointer}")
    return selected


def _valid_datetime(value: str) -> bool:
    try:
        selected = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return "T" in value and selected.tzinfo is not None


def validate_json_schema(
    value: Any,
    schema: dict[str, Any],
    *,
    root_schema: dict[str, Any] | None = None,
    path: str = "$",
) -> None:
    """Validate the schema features used by the acceptance contracts.

    Unsupported keywords are rejected instead of silently ignored.  Annotation
    keywords are explicitly allowed.  This is deliberately strict so adding a
    new security-relevant schema keyword cannot weaken verification unnoticed.
    """

    root = root_schema or schema
    supported = {
        "$schema",
        "$id",
        "$defs",
        "$ref",
        "title",
        "description",
        "type",
        "const",
        "enum",
        "oneOf",
        "anyOf",
        "allOf",
        "not",
        "required",
        "properties",
        "additionalProperties",
        "patternProperties",
        "minProperties",
        "maxProperties",
        "items",
        "prefixItems",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
    }
    unknown = sorted(set(schema) - supported)
    if unknown:
        raise SchemaValidationError(
            f"{path}: unsupported schema keyword(s): {', '.join(unknown)}"
        )

    if "$ref" in schema:
        validate_json_schema(
            value,
            _resolve_pointer(root, str(schema["$ref"])),
            root_schema=root,
            path=path,
        )
        siblings = {key: item for key, item in schema.items() if key != "$ref"}
        if siblings:
            validate_json_schema(value, siblings, root_schema=root, path=path)
        return

    expected_type = schema.get("type")
    if expected_type is not None:
        type_values = [expected_type] if isinstance(expected_type, str) else expected_type
        if not isinstance(type_values, list) or not all(
            isinstance(item, str) for item in type_values
        ):
            raise SchemaValidationError(f"{path}: schema type must be a string or list")
        if not any(_matches_type(value, item) for item in type_values):
            raise SchemaValidationError(
                f"{path}: expected type {type_values}, got {type(value).__name__}"
            )

    if "const" in schema and not _json_equal(value, schema["const"]):
        raise SchemaValidationError(f"{path}: value does not match const")
    if "enum" in schema and not any(
        _json_equal(value, candidate) for candidate in schema["enum"]
    ):
        raise SchemaValidationError(f"{path}: value is not in enum")

    for keyword, expected_matches in (("oneOf", 1), ("anyOf", None)):
        if keyword not in schema:
            continue
        alternatives = schema[keyword]
        if not isinstance(alternatives, list) or not alternatives:
            raise SchemaValidationError(f"{path}: {keyword} must be non-empty")
        matches = 0
        for alternative in alternatives:
            try:
                validate_json_schema(
                    value,
                    alternative,
                    root_schema=root,
                    path=path,
                )
            except SchemaValidationError:
                continue
            matches += 1
        if expected_matches is not None and matches != expected_matches:
            raise SchemaValidationError(
                f"{path}: oneOf matched {matches} schemas instead of one"
            )
        if expected_matches is None and matches == 0:
            raise SchemaValidationError(f"{path}: anyOf matched no schema")

    for part in schema.get("allOf", []):
        validate_json_schema(value, part, root_schema=root, path=path)
    if "not" in schema:
        try:
            validate_json_schema(value, schema["not"], root_schema=root, path=path)
        except SchemaValidationError:
            pass
        else:
            raise SchemaValidationError(f"{path}: value matched forbidden schema")

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise SchemaValidationError(f"{path}: missing required keys {missing}")
        if len(value) < int(schema.get("minProperties", 0)):
            raise SchemaValidationError(f"{path}: too few properties")
        if "maxProperties" in schema and len(value) > int(schema["maxProperties"]):
            raise SchemaValidationError(f"{path}: too many properties")
        properties = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        matched: set[str] = set()
        for key, child in properties.items():
            if key in value:
                matched.add(key)
                validate_json_schema(
                    value[key], child, root_schema=root, path=f"{path}.{key}"
                )
        for key, item in value.items():
            for pattern, child in patterns.items():
                if re.search(pattern, key):
                    matched.add(key)
                    validate_json_schema(
                        item, child, root_schema=root, path=f"{path}.{key}"
                    )
        extras = sorted(set(value) - matched)
        additional = schema.get("additionalProperties", True)
        if additional is False and extras:
            raise SchemaValidationError(f"{path}: unknown properties {extras}")
        if isinstance(additional, dict):
            for key in extras:
                validate_json_schema(
                    value[key],
                    additional,
                    root_schema=root,
                    path=f"{path}.{key}",
                )

    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            raise SchemaValidationError(f"{path}: too few items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise SchemaValidationError(f"{path}: too many items")
        if schema.get("uniqueItems") is True:
            for index, item in enumerate(value):
                if any(_json_equal(item, earlier) for earlier in value[:index]):
                    raise SchemaValidationError(f"{path}: duplicate array item")
        prefix = schema.get("prefixItems", [])
        for index, child in enumerate(prefix):
            if index < len(value):
                validate_json_schema(
                    value[index], child, root_schema=root, path=f"{path}[{index}]"
                )
        items = schema.get("items")
        if isinstance(items, dict):
            start = len(prefix) if prefix else 0
            for index, item in enumerate(value[start:], start=start):
                validate_json_schema(
                    item, items, root_schema=root, path=f"{path}[{index}]"
                )
        elif items is False and len(value) > len(prefix):
            raise SchemaValidationError(f"{path}: additional array items forbidden")

    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            raise SchemaValidationError(f"{path}: string too short")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise SchemaValidationError(f"{path}: string too long")
        if "pattern" in schema and re.search(str(schema["pattern"]), value) is None:
            raise SchemaValidationError(f"{path}: string does not match pattern")
        if schema.get("format") == "date-time" and not _valid_datetime(value):
            raise SchemaValidationError(f"{path}: invalid date-time")
        if schema.get("format") not in (None, "date-time"):
            raise SchemaValidationError(
                f"{path}: unsupported format {schema.get('format')}"
            )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaValidationError(f"{path}: number below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaValidationError(f"{path}: number above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise SchemaValidationError(f"{path}: number below exclusiveMinimum")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            raise SchemaValidationError(f"{path}: number above exclusiveMaximum")
        if "multipleOf" in schema:
            multiple = schema["multipleOf"]
            if multiple == 0 or abs((value / multiple) - round(value / multiple)) > 1e-9:
                raise SchemaValidationError(f"{path}: number is not a multipleOf")


def read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def resolve_artifact(root: Path, reference: dict[str, Any]) -> Path:
    relative = reference.get("path")
    if not isinstance(relative, str) or not relative:
        raise ValueError("artifact path is missing")
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("artifact path escapes evidence root")
    root_resolved = root.resolve(strict=True)
    candidate = root_resolved / relative_path
    if candidate.is_symlink():
        raise ValueError("artifact path may not be a symlink")
    selected = candidate.resolve(strict=True)
    if selected == root_resolved or root_resolved not in selected.parents:
        raise ValueError("artifact resolved outside evidence root")
    current = selected.parent
    while current != root_resolved:
        if current.is_symlink():
            raise ValueError("artifact parent may not be a symlink")
        current = current.parent
    if not selected.is_file():
        raise ValueError("artifact is not a regular file")
    expected_size = reference.get("size_bytes")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool):
        raise ValueError("artifact size is invalid")
    if selected.stat().st_size != expected_size:
        raise ValueError("artifact size mismatch")
    expected_sha = reference.get("sha256")
    if sha256_file(selected) != expected_sha:
        raise ValueError("artifact sha256 mismatch")
    return selected


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("artifact is not a PNG")
    if header[12:16] != b"IHDR":
        raise ValueError("PNG is missing IHDR")
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        raise ValueError("PNG dimensions are invalid")
    return width, height


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"NDJSON line {line_number} is not an object")
        records.append(value)
    return records


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True
