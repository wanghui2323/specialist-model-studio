"""One operator-owned isolation configuration for every execution phase."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .errors import ContractError
from .io_utils import read_json


def execution_runtime_config(path: Path | None = None) -> dict[str, Any]:
    selected = path or Path.home() / ".local/share/specialist-model-studio/execution-runtime.json"
    if not selected.is_file() or selected.is_symlink():
        return {}
    value = read_json(selected)
    if not isinstance(value, dict):
        raise ContractError("execution runtime configuration must be an object")
    return value


def execution_root(default: Path, *, explicit: Path | None = None) -> Path:
    configured = execution_runtime_config()
    selected = explicit or os.environ.get("MODEL_HARNESS_ISOLATED_ROOT") or configured.get("isolated_root") or default
    if not isinstance(selected, (str, Path)):
        raise ContractError("isolated execution root must be an operator-owned path")
    return Path(selected).expanduser().resolve()
