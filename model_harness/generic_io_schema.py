"""Offline JSON Schema checks for the generic inference transport protocol.

This validates declared structure, not model quality or media semantics. JSON
Schema 2020-12 is the one explicit dialect; references never retrieve resources.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import NoSuchResource, Unresolvable

from .errors import ContractError

_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_MAX_SCHEMA_BYTES = 128 * 1024
_SCHEMA_MAPS = {"$defs", "definitions", "properties", "patternProperties", "dependentSchemas"}
_SCHEMA_VALUES = {"additionalProperties", "unevaluatedProperties", "propertyNames", "items", "contains",
                  "not", "if", "then", "else", "unevaluatedItems", "contentSchema"}
_SCHEMA_ARRAYS = {"allOf", "anyOf", "oneOf", "prefixItems"}


def _deny_retrieval(uri: str):
    # Never delegate a URI to the network, filesystem, or a custom resolver.
    raise NoSuchResource(ref=uri)


def _json_shape(value: Any, *, label: str, maximum_nodes: int = 250_000) -> None:
    nodes = 0
    def visit(item: Any, depth: int):
        nonlocal nodes
        nodes += 1
        if nodes > maximum_nodes or depth > 64:
            raise ContractError(f"{label} exceeds structural validation limits")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ContractError(f"{label} must use JSON string keys")
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ContractError(f"{label} contains a non-finite number")
        elif item is not None and not isinstance(item, (str, bool, int, float)):
            raise ContractError(f"{label} must contain JSON data")
    visit(value, 0)


def _validator(schema: Any, *, label: str) -> Draft202012Validator:
    if not isinstance(schema, dict):
        raise ContractError(f"{label} must be a JSON Schema object")
    _json_shape(schema, label=label, maximum_nodes=16_000)
    try:
        schema_bytes = json.dumps(schema, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, TypeError):
        raise ContractError(f"{label} is not valid UTF-8 JSON") from None
    if len(schema_bytes) > _MAX_SCHEMA_BYTES:
        raise ContractError(f"{label} exceeds the schema size limit")
    visited: set[int] = set()

    def pointer(ref: str) -> Any:
        current = schema
        if ref == "#":
            return current
        try:
            segments = unquote(ref[2:], errors="strict").split("/")
        except UnicodeError:
            raise ContractError(f"{label} contains an invalid local schema reference") from None
        for segment in segments:
            if re.search(r"~(?:[^01]|$)", segment):
                raise ContractError(f"{label} contains an invalid local schema reference")
            token = segment.replace("~1", "/").replace("~0", "~")
            try:
                if isinstance(current, list) and not re.fullmatch(r"0|[1-9][0-9]*", token):
                    raise ValueError("invalid JSON pointer index")
                current = current[int(token)] if isinstance(current, list) else current[token]
            except (KeyError, IndexError, TypeError, ValueError):
                raise ContractError(f"{label} contains an unresolved local schema reference") from None
        if not isinstance(current, (dict, bool)):
            raise ContractError(f"{label} reference must target a schema")
        return current

    def inspect(node: Any):
        if not isinstance(node, dict) or id(node) in visited:
            return
        visited.add(id(node))
        if "$schema" in node and (not isinstance(node["$schema"], str) or node["$schema"] not in {_DIALECT, _DIALECT + "#"}):
            raise ContractError(f"{label} requires JSON Schema Draft 2020-12")
        if "$id" in node and node is not schema:
            raise ContractError(f"{label} cannot redefine the local schema resource")
        if "$recursiveRef" in node:
            raise ContractError(f"{label} requires Draft 2020-12 reference syntax")
        for key in ("$ref", "$dynamicRef"):
            if key in node:
                ref = node[key]
                if not isinstance(ref, str) or not (ref == "#" or ref.startswith("#/")):
                    raise ContractError(f"{label} permits only local JSON pointer references")
                inspect(pointer(ref))
        for key, child in node.items():
            if key in _SCHEMA_MAPS and isinstance(child, dict):
                for value in child.values():
                    inspect(value)
            elif key in _SCHEMA_VALUES:
                inspect(child)
            elif key in _SCHEMA_ARRAYS and isinstance(child, list):
                for value in child:
                    inspect(value)
    inspect(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except (SchemaError, ValueError, TypeError, RecursionError):
        # The library's full exception includes schema literals and instance
        # values. Public failures intentionally expose neither.
        raise ContractError(f"{label} is not a valid Draft 2020-12 schema") from None
    return Draft202012Validator(schema, registry=Registry(retrieve=_deny_retrieval))


def validate_schema_definition(schema: Any, *, label: str = "inference schema") -> None:
    _validator(schema, label=label)


def _validate(value: Any, schema: Mapping[str, Any], *, label: str) -> None:
    validator = _validator(schema, label=label + " schema")
    _json_shape(value, label=label)
    try:
        validator.validate(value)
    except ValidationError as error:
        # Keyword names are library identifiers; do not include instance paths,
        # user-controlled property names, the schema body, or error.message.
        keyword = error.validator
        detail = keyword if isinstance(keyword, str) and keyword in Draft202012Validator.VALIDATORS else "structure"
        raise ContractError(f"{label} does not match the declared schema ({detail})") from None
    except (Unresolvable, RecursionError, ValueError, TypeError):
        raise ContractError(f"{label} schema could not be resolved or evaluated offline") from None


def validate_input_file(path: Path, declaration: Mapping[str, Any]) -> dict[str, Any]:
    """Check declared JSON/text structure; preserve other inputs as opaque bytes."""
    schema = declaration.get("schema")
    if "schema" not in declaration:
        return {"status": "not_declared", "scope": "none", "schema_declared": False}
    validate_schema_definition(schema)
    suffix = Path(path).suffix.lower()
    if suffix not in {".json", ".txt"}:
        return {"status": "worker_validation_required", "scope": "worker_format_validation", "schema_declared": True}
    limit = declaration.get("max_bytes")
    if type(limit) is not int or not 1 <= limit <= 25 * 1024 * 1024:
        raise ContractError("inference input has no valid declared byte limit")
    try:
        with Path(path).open("rb") as handle:
            payload = handle.read(limit + 1)
        if len(payload) > limit:
            raise ContractError("inference input exceeds its declared byte limit")
        text = payload.decode("utf-8-sig" if suffix == ".json" else "utf-8", errors="strict")
        if suffix == ".json":
            def pairs(items):
                value = {}
                for key, child in items:
                    if key in value:
                        raise ValueError("duplicate JSON key")
                    value[key] = child
                return value
            def reject_constant(value):
                raise ValueError("non-finite JSON")
            value = json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant)
        else:
            value = text
    except ContractError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise ContractError("inference input is not valid UTF-8 JSON" if suffix == ".json" else "inference input is not valid UTF-8 text") from None
    _validate(value, schema, label="inference input")
    return {"status": "passed", "scope": "host_json" if suffix == ".json" else "host_utf8_text", "schema_declared": True}


def validate_output_result(result: Mapping[str, Any], declaration: Mapping[str, Any]) -> dict[str, Any]:
    """The schema applies to the whole infer_result.json envelope."""
    if "output_schema" not in declaration:
        return {"status": "not_declared", "scope": "none", "schema_declared": False}
    _validate(result, declaration["output_schema"], label="inference output envelope")
    return {"status": "passed", "scope": "host_infer_result_envelope", "schema_declared": True}
