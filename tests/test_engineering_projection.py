from __future__ import annotations

import unittest
from copy import deepcopy

from model_harness.agent_bridge import agent_public_projection
from model_harness.conversation_payloads import engineering_public_projection
from model_harness.isolated_execution import ExecutionBundle


class EngineeringProjectionTests(unittest.TestCase):
    def test_only_workspace_protocol_virtual_working_directory_survives(self):
        payload = {"execution_workspace": {"protocol": {"working_directory": "/workspace/output"},
                   "execution_spec_schema": {"x-protocol": {"working_directory": "/workspace/output"}}},
                   "working_directory": "/workspace/output", "logs": {"protocol": {"working_directory": "/workspace/output"}}}
        projected = engineering_public_projection(payload)
        self.assertEqual(projected["execution_workspace"]["protocol"]["working_directory"], "/workspace/output")
        self.assertEqual(projected["execution_workspace"]["execution_spec_schema"]["x-protocol"]["working_directory"], "/workspace/output")
        self.assertNotIn("working_directory", projected)
        self.assertNotIn("working_directory", projected["logs"]["protocol"])
        self.assertNotIn("working_directory", agent_public_projection(payload)["execution_workspace"]["protocol"])
        for unsafe in ("/Users/private/cache", "/tmp/host-cache", "/workspace/output/../private", "/workspace/output\\private", "/workspace/output\nprivate"):
            payload["execution_workspace"]["protocol"]["working_directory"] = unsafe
            self.assertNotIn("working_directory", engineering_public_projection(payload)["execution_workspace"]["protocol"])

    def test_schema_business_keys_are_not_host_controls(self):
        schema = {"type": "object", "required": ["root", "source_path", "cwd"], "properties": {
            "root": {"type": "number"}, "source_path": {"type": "string"}, "cwd": {"type": "boolean"},
            "branch_root": {"type": "array", "items": {"type": "number"}},
        }}
        payload = {"execution_spec_schema": schema, "root": "/Users/private/work", "cwd": "/tmp/private", "note": "host /Users/private/data"}
        original = deepcopy(payload)
        result = engineering_public_projection(payload)
        self.assertEqual(result["execution_spec_schema"], schema)
        self.assertNotIn("root", result)
        self.assertNotIn("cwd", result)
        self.assertNotIn("/Users/private", result["note"])
        self.assertEqual(payload, original)
        self.assertNotIn("root", agent_public_projection(payload)["execution_spec_schema"]["properties"])

    def test_virtual_paths_and_literal_markers_never_change_nonpath_data(self):
        source = 'marker = "__SMS_VIRTUAL_input__"\nother = "__SMS_SANDBOX_PATH_0__"\np = "/workspace/input/a b.txt"\n'
        payload = {"execution_spec": {"bundle": {"files": {"root": source, "source_path": "print(1)"}}, "config": {"root": 0, "cwd": False, "source_path": "/Users/private/file", "nonpath": "__SMS_VIRTUAL_output__"}}, "outside": "/usr/private/data", "traversal": "/workspace/input/../private"}
        result = engineering_public_projection(payload)
        self.assertEqual(result["execution_spec"]["bundle"]["files"]["root"], source)
        self.assertEqual(result["execution_spec"]["bundle"]["files"]["source_path"], "print(1)")
        self.assertEqual(result["execution_spec"]["config"]["root"], 0)
        self.assertIs(result["execution_spec"]["config"]["cwd"], False)
        self.assertEqual(result["execution_spec"]["config"]["nonpath"], "__SMS_VIRTUAL_output__")
        self.assertNotIn("source_path", result["execution_spec"]["config"])
        self.assertEqual(result["outside"], "[local-path-redacted]")
        self.assertEqual(result["traversal"], "[local-path-redacted]")

    def test_only_frozen_proposal_source_and_argv_are_exact_content(self):
        code = 'cache = "/tmp/cache"\npython = "/usr/bin/python"\nmarker = "__SMS_VIRTUAL_input__"\n'
        bundle = ExecutionBundle.create(files={"root": code, "source_path": "print(1)\n"}, stages={"qualify": ["/usr/bin/python", "/workspace/source/root", "--cache", "/tmp/cache"]}, image="python@sha256:" + "a" * 64)
        proposal = {"object_type": "ExecutionProposal", "task_id": "task-a", "proposal_id": "execution-" + "e" * 24, "proposal_sha256": "f" * 64, "base_spec_revision": 1,
                    "execution_spec": {"bundle": bundle.to_dict(), "bundle_sha256": bundle.digest}, "dataset": {"root": "/Users/private/dataset"},
                    "logs": {"code": code, "argv": ["/usr/bin/python", "/tmp/cache"], "root": "/Users/private/logs"}}
        payload = {"proposal": proposal}
        projected = engineering_public_projection(payload)
        self.assertEqual(projected["proposal"]["execution_spec"]["bundle"], bundle.to_dict())
        self.assertEqual(ExecutionBundle.from_dict(projected["proposal"]["execution_spec"]["bundle"]).digest, bundle.digest)
        self.assertEqual(projected["proposal"]["proposal_sha256"], proposal["proposal_sha256"])
        self.assertNotIn("root", projected["proposal"]["dataset"])
        self.assertNotIn("/tmp/cache", projected["proposal"]["logs"]["code"])
        self.assertNotIn("/usr/bin", str(projected["proposal"]["logs"]["argv"]))
        listed = engineering_public_projection({"proposals": [proposal]})
        self.assertEqual(listed["proposals"][0]["execution_spec"]["bundle"], bundle.to_dict())
        unbound = engineering_public_projection({"execution_spec": proposal["execution_spec"]})
        self.assertNotIn("/tmp/cache", unbound["execution_spec"]["bundle"]["files"]["root"])
        invalid = deepcopy(payload); invalid["proposal"]["execution_spec"]["bundle_sha256"] = "0" * 64
        self.assertNotIn("/usr/bin", str(engineering_public_projection(invalid)["proposal"]["execution_spec"]["bundle"]["stages"]))


if __name__ == "__main__":
    unittest.main()
