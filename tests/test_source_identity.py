from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from model_harness.server import create_app
from model_harness.source_identity import (
    STUDIO_SOURCE_ROOT_ENV,
    resolve_runtime_source_root,
)


def _complete_source_checkout(root: Path) -> Path:
    for relative in (
        "pyproject.toml",
        "scripts/start_conversation_harness.sh",
        "integrations/deepseek-harness/package.json",
        "acceptance/dsh-runtime/package.json",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test\n", encoding="utf-8")
    return root


class SourceIdentityTests(unittest.TestCase):
    def test_non_editable_runtime_in_checkout_venv_uses_release_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            release = _complete_source_checkout(Path(temp_dir) / "release")
            installed_server = (
                release
                / ".venv/lib/python3.12/site-packages/model_harness/server.py"
            )
            with mock.patch.dict(
                os.environ,
                {STUDIO_SOURCE_ROOT_ENV: ""},
                clear=False,
            ):
                resolved = resolve_runtime_source_root(
                    module_file=installed_server,
                    prefix=release / ".venv",
                )

            self.assertEqual(resolved, release.resolve())

    def test_server_runtime_identity_honors_explicit_release_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            release = _complete_source_checkout(Path(temp_dir) / "release")
            runs = Path(temp_dir) / "runs"
            with mock.patch.dict(
                os.environ,
                {STUDIO_SOURCE_ROOT_ENV: str(release)},
                clear=False,
            ):
                app = create_app(runs, conversation_url="http://127.0.0.1:3999")
                with TestClient(app) as client:  # type: ignore[misc]
                    identity = client.get("/runtime").json()["runtime_identity"]

            self.assertEqual(identity["source_root"], str(release.resolve()))


if __name__ == "__main__":
    unittest.main()
