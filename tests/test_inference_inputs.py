from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.inference_inputs import (
    InferenceInputError,
    InferenceInputStore,
)
from model_harness.object_refs import exact_object_ref_endpoint, normalize_object_ref
from model_harness.server import create_app
from tests.test_l4_task_api import AGENT_BRIDGE_HEADERS, _completed_image_task, _new_image


def _walk_strings(value: object) -> list[str]:
    if isinstance(value, dict):
        values: list[str] = []
        for key, item in value.items():
            values.append(str(key))
            values.extend(_walk_strings(item))
        return values
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(_walk_strings(item))
        return values
    return [value] if isinstance(value, str) else []


class InferenceInputStoreTests(unittest.TestCase):
    def test_store_uses_opaque_identity_and_rejects_tamper_or_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = InferenceInputStore(temporary)
            record = store.stage(
                task_id="task-one",
                run_id="run-one",
                payload=b'{"area_sqm": 80}',
                filename="one-row.json",
                sample_type="tabular",
            )
            self.assertTrue(record["inference_input_id"].startswith("inference-input-"))
            self.assertNotIn(str(Path(temporary).resolve()), json.dumps(record))
            with self.assertRaisesRegex(InferenceInputError, "another run"):
                store.resolve_staged(
                    task_id="task-one",
                    run_id="run-two",
                    inference_input_id=record["inference_input_id"],
                )
            with self.assertRaisesRegex(InferenceInputError, "filename"):
                store.stage(
                    task_id="task-one",
                    run_id="run-one",
                    payload=b"not-empty",
                    filename="../escape.json",
                    sample_type="tabular",
                )

            reserved, _ = store.reserve(
                task_id="task-one",
                run_id="run-one",
                inference_input_id=record["inference_input_id"],
                expected_sha256=record["sha256"],
            )
            self.assertEqual(reserved["status"], "consuming")
            completed = store.complete(
                task_id="task-one",
                run_id="run-one",
                inference_input_id=record["inference_input_id"],
                outcome={"status": "passed"},
            )
            self.assertEqual(completed["status"], "consumed")
            with self.assertRaisesRegex(InferenceInputError, "already used"):
                store.resolve_staged(
                    task_id="task-one",
                    run_id="run-one",
                    inference_input_id=record["inference_input_id"],
                )

            tampered = store.stage(
                task_id="task-one",
                run_id="run-one",
                payload=b'{"area_sqm": 81}',
                filename="tampered.json",
                sample_type="tabular",
            )
            blob = (
                Path(temporary)
                / "tasks"
                / "task-one"
                / "inference_inputs"
                / tampered["inference_input_id"]
                / "sample.json"
            )
            os.chmod(blob, 0o600)
            blob.write_bytes(b'{"area_sqm": 99}')
            with self.assertRaisesRegex(InferenceInputError, "digest changed"):
                store.get("task-one", tampered["inference_input_id"])


@unittest.skipIf(TestClient is None, "server extra is not installed")
class InferenceInputApiTests(unittest.TestCase):
    def test_uploaded_input_requires_one_exact_backend_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(
                os.environ,
                {"MODEL_HARNESS_AGENT_BRIDGE_TOKEN": "test-agent-bridge-token"},
            ):
                app = create_app(Path(temporary) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                task_id, run_id = _completed_image_task(client, app)
                uploaded = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/inference-inputs",
                    content=_new_image(),
                    headers={
                        "Content-Type": "image/png",
                        "X-Filename": "new-red-part.png",
                        "X-Sample-Type": "image",
                    },
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                body = uploaded.json()
                inference_input = body["inference_input"]
                input_id = inference_input["inference_input_id"]
                self.assertEqual(inference_input["status"], "staged")
                self.assertNotIn(str(Path(temporary).resolve()), _walk_strings(body))
                self.assertFalse(
                    any("path" in value.lower() for value in body.keys())
                )
                ref = normalize_object_ref(
                    body["object_refs"][0],
                    expected_task_id=task_id,
                    expected_run_id=run_id,
                )
                self.assertEqual(
                    exact_object_ref_endpoint(ref),
                    f"/tasks/{quote(task_id, safe='')}/runs/{quote(run_id, safe='')}"
                    f"/inference-inputs/{quote(input_id, safe='')}",
                )

                denied = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/sample-inference-authorizations",
                    json={
                        "inference_input_id": input_id,
                        "inference_input_sha256": inference_input["sha256"],
                        "approval": {
                            "actor": "user",
                            "checkpoint_id": "native-sample-inference-approval",
                        },
                    },
                )
                self.assertEqual(denied.status_code, 403, denied.text)

                authorized = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/sample-inference-authorizations",
                    headers=AGENT_BRIDGE_HEADERS,
                    json={
                        "inference_input_id": input_id,
                        "inference_input_sha256": inference_input["sha256"],
                        "approval": {
                            "actor": "user",
                            "checkpoint_id": "native-sample-inference-approval",
                        },
                    },
                )
                self.assertEqual(authorized.status_code, 201, authorized.text)
                authorization_body = authorized.json()
                authorization = authorization_body[
                    "sample_inference_authorization"
                ]
                self.assertEqual(authorization["action"], "run_sample_inference")
                self.assertEqual(authorization["scope"]["run_id"], run_id)
                self.assertEqual(
                    authorization["scope"]["inference_input_id"], input_id
                )
                self.assertEqual(
                    authorization["scope"]["inference_input_sha256"],
                    inference_input["sha256"],
                )

                executed = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/inference-inputs/"
                    f"{input_id}/execute",
                    json={
                        "sample_inference_authorization_id": authorization[
                            "authorization_id"
                        ],
                        "authorization_token": authorization_body[
                            "authorization_token"
                        ],
                        "sample_inference_request_sha256": authorization[
                            "scope_sha256"
                        ],
                    },
                )
                self.assertEqual(executed.status_code, 201, executed.text)
                executed_body = executed.json()
                self.assertEqual(executed_body["sample_inference"]["status"], "passed")
                self.assertEqual(executed_body["inference_input"]["status"], "consumed")
                self.assertEqual(
                    executed_body["sample_inference_authorization"]["status"],
                    "consumed",
                )
                self.assertNotIn(
                    str(Path(temporary).resolve()), _walk_strings(executed_body)
                )

                replayed = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/inference-inputs/"
                    f"{input_id}/execute",
                    json={
                        "sample_inference_authorization_id": authorization[
                            "authorization_id"
                        ],
                        "authorization_token": authorization_body[
                            "authorization_token"
                        ],
                        "sample_inference_request_sha256": authorization[
                            "scope_sha256"
                        ],
                    },
                )
                self.assertEqual(replayed.status_code, 409, replayed.text)

                other_task = client.post(
                    "/tasks",
                    json={"name": "other", "business_goal": "cross-task isolation"},
                ).json()["task"]["task_id"]
                cross_task = client.get(
                    f"/tasks/{other_task}/runs/{run_id}/inference-inputs/{input_id}"
                )
                self.assertEqual(cross_task.status_code, 409, cross_task.text)

    def test_upload_rejects_filename_escape_before_persisting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(
                os.environ,
                {"MODEL_HARNESS_AGENT_BRIDGE_TOKEN": "test-agent-bridge-token"},
            ):
                app = create_app(Path(temporary) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                task_id, run_id = _completed_image_task(client, app)
                rejected = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/inference-inputs",
                    content=_new_image(),
                    headers={
                        "X-Filename": "..%2Fescape.png",
                        "X-Sample-Type": "image",
                    },
                )
                self.assertEqual(rejected.status_code, 422, rejected.text)
                listed = client.get(
                    f"/tasks/{task_id}/runs/{run_id}/inference-inputs"
                )
                self.assertEqual(listed.status_code, 200, listed.text)
                self.assertEqual(listed.json()["inference_inputs"], [])


if __name__ == "__main__":
    unittest.main()
