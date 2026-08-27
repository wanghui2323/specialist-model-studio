from __future__ import annotations

import os
from typing import Any


TEST_AGENT_BRIDGE_TOKEN = "test-agent-bridge-token"
AGENT_BRIDGE_HEADERS = {
    "X-Model-Harness-Agent-Token": TEST_AGENT_BRIDGE_TOKEN,
}

# Test modules import this helper before constructing their FastAPI app.
os.environ.setdefault(
    "MODEL_HARNESS_AGENT_BRIDGE_TOKEN",
    TEST_AGENT_BRIDGE_TOKEN,
)


def request_task_run_authorization(
    client: Any,
    task_id: str,
    *,
    checkpoint_id: str | None = None,
) -> Any:
    task_response = client.get(f"/tasks/{task_id}")
    assert task_response.status_code == 200, task_response.text
    task = task_response.json()["task"]
    return client.post(
        f"/tasks/{task_id}/run-authorizations",
        json={
            "contract_sha256": task["confirmed_contract_sha256"],
            "dataset_id": task["dataset_id"],
            "dataset_fingerprint_sha256": task["dataset_report"][
                "fingerprint_sha256"
            ],
            "spec_revision": task["current_spec_revision"],
            "approval": {
                "actor": "user",
                "checkpoint_id": checkpoint_id or f"native-run:{task_id}",
            },
        },
        headers=AGENT_BRIDGE_HEADERS,
    )


def authorize_task_run(
    client: Any,
    task_id: str,
    *,
    checkpoint_id: str | None = None,
) -> dict[str, Any]:
    issued = request_task_run_authorization(
        client,
        task_id,
        checkpoint_id=checkpoint_id,
    )
    assert issued.status_code == 201, issued.text
    return issued.json()


def start_authorized_task_run(
    client: Any,
    task_id: str,
    *,
    checkpoint_id: str | None = None,
) -> Any:
    issued = authorize_task_run(
        client,
        task_id,
        checkpoint_id=checkpoint_id,
    )
    authorization = issued["run_authorization"]
    return client.post(
        f"/tasks/{task_id}/runs",
        json={
            "run_authorization_id": authorization["authorization_id"],
            "authorization_token": issued["authorization_token"],
            "run_request_sha256": authorization["scope_sha256"],
        },
    )
