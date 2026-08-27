from __future__ import annotations

from typing import Any


IDENTITY_FIELDS = (
    "contract_revision_id",
    "contract_sha256",
    "task_id",
    "spec_revision_id",
    "dataset_id",
    "dataset_fingerprint_sha256",
)


def contract_confirmation_payload(
    client: Any,
    task_id: str,
    *,
    checkpoint_id: str | None = None,
    actor: str = "test-user",
) -> dict[str, Any]:
    response = client.get(f"/tasks/{task_id}")
    if response.status_code != 200:
        raise AssertionError(response.text)
    revision = response.json()["task"]["contract_revision"]
    return {
        "data_authorized": True,
        "labels_reviewed": True,
        "gates_reviewed": True,
        "expected_contract_revision": {
            field: revision[field] for field in IDENTITY_FIELDS
        },
        "approval": {
            "actor": actor,
            "checkpoint_id": checkpoint_id or f"checkpoint:{task_id}",
        },
    }
