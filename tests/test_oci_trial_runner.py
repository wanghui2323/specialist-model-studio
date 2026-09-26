"""Trusted runner protocol tests only; no downloads, container or model execution."""

from contextlib import ExitStack, contextmanager, redirect_stderr
import base64
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch


RUNNER_PATH = Path(__file__).resolve().parents[1] / "model_harness" / "oci_trial_runner.py"
SPEC = importlib.util.spec_from_file_location("oci_trial_runner_protocol_tests", RUNNER_PATH)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def encode(packet):
    return json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode()


def sign_manifest(packet):
    raw = json.dumps(packet["asset"]["files"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    packet["asset"]["manifest_sha256"] = sha(raw)
    return packet


def packet_fixture():
    # Opaque sentinel bytes intentionally are NOT a runnable model/image.
    blobs = {"model.onnx": b"opaque-model-fixture", "config.json": b'{"fixture":true}', "sample": b"opaque-sample-fixture"}
    packet = {
        "schema_version": "1.0", "task_id": "task-test", "trial_id": "trial-test",
        "plan_sha256": "a" * 64, "input_sha256": sha(blobs["sample"]),
        "asset": {"files": [{"relative_path": name, "size_bytes": len(value), "sha256": sha(value)} for name, value in blobs.items() if name != "sample"]},
        "blobs": {name: base64.b64encode(value).decode() for name, value in blobs.items()},
    }
    return sign_manifest(packet), blobs


@contextmanager
def guard_facts(*, marker=True, uid=65534, gid=65534, network=("lo",), env=None):
    # These are mocked facts only: no container or /work directory is created.
    with ExitStack() as stack:
        stack.enter_context(patch.object(runner.sys, "platform", "linux"))
        stack.enter_context(patch.object(Path, "is_file", return_value=marker))
        stack.enter_context(patch.object(runner.os, "getuid", return_value=uid))
        stack.enter_context(patch.object(runner.os, "getgid", return_value=gid))
        stack.enter_context(patch.object(Path, "iterdir", return_value=iter(Path("/sys/class/net") / name for name in network)))
        stack.enter_context(patch.dict(runner.os.environ, env or {}, clear=True))
        yield


class OciTrialPacketTests(unittest.TestCase):
    def assert_rejected(self, packet, code):
        with self.assertRaisesRegex(ValueError, code):
            runner.validate_packet(encode(packet))

    def test_correct_manifest_and_opaque_blobs_decode_without_model_import(self):
        packet, blobs = packet_fixture()
        with patch.dict(sys.modules, {"onnxruntime": None, "numpy": None, "PIL": None}):
            parsed, decoded = runner.validate_packet(encode(packet))
        self.assertEqual(parsed, packet)
        self.assertEqual(decoded, blobs)

    def test_readme_manifest_metadata_does_not_become_an_execution_blob(self):
        packet, blobs = packet_fixture()
        packet["asset"]["files"].append({"relative_path": "README.md", "size_bytes": 8, "sha256": sha(b"metadata")})
        parsed, decoded = runner.validate_packet(encode(sign_manifest(packet)))
        self.assertEqual(len(parsed["asset"]["files"]), 3)
        self.assertEqual(decoded, blobs)
        self.assertNotIn("README.md", decoded)

    def test_packet_size_limit_precedes_json_parsing(self):
        for raw in (b"", b"x" * (runner.MAX_PACKET_BYTES + 1)):
            with self.subTest(length=len(raw)), self.assertRaisesRegex(ValueError, "packet_size_limit"):
                runner.validate_packet(raw)

    def test_packet_schema_and_container_types(self):
        for packet in (None, [], {}, {"schema_version": "2.0"}):
            with self.subTest(packet=packet):
                self.assert_rejected(packet, "invalid_packet")
        packet, _ = packet_fixture()
        for field, value in (("asset", []), ("blobs", [])):
            invalid = copy.deepcopy(packet); invalid[field] = value
            self.assert_rejected(invalid, "invalid_asset_packet")

    def test_task_and_trial_identities_fail_closed(self):
        for field in ("task_id", "trial_id"):
            for value in (None, 1, "", "../task", "/tmp/id", "id with space", "id\n", "x" * 129):
                packet, _ = packet_fixture(); packet[field] = value
                with self.subTest(field=field, value=value):
                    self.assert_rejected(packet, "invalid_identity")

    def test_plan_and_input_sha_require_lowercase_complete_digests(self):
        for field in ("plan_sha256", "input_sha256"):
            for value in (None, 1, "A" * 64, "0" * 63, "g" * 64, ""):
                packet, _ = packet_fixture(); packet[field] = value
                with self.subTest(field=field, value=value):
                    self.assert_rejected(packet, "invalid_digest")

    def test_blob_names_are_exact_model_config_and_sample_only(self):
        for name in ("model.onnx", "config.json", "sample"):
            packet, _ = packet_fixture(); del packet["blobs"][name]
            self.assert_rejected(packet, "invalid_asset_packet")
        for name in ("README.md", "../model.onnx", "/tmp/sample", "code.py", "model.onnx.data"):
            packet, _ = packet_fixture(); packet["blobs"][name] = "eA=="
            self.assert_rejected(packet, "invalid_asset_packet")

    def test_manifest_is_a_list_of_records_with_no_duplicate_paths(self):
        for value in (None, {}, [None], [1]):
            packet, _ = packet_fixture(); packet["asset"]["files"] = value
            self.assert_rejected(packet, "invalid_manifest")
        packet, _ = packet_fixture(); packet["asset"]["files"].append(copy.deepcopy(packet["asset"]["files"][0]))
        self.assert_rejected(sign_manifest(packet), "duplicate_asset_file")

    def test_manifest_digest_change_is_rejected_before_blob_use(self):
        packet, _ = packet_fixture(); packet["asset"]["manifest_sha256"] = "0" * 64
        self.assert_rejected(packet, "manifest_digest_mismatch")
        packet, _ = packet_fixture(); packet["asset"]["files"][0]["size_bytes"] += 1
        self.assert_rejected(packet, "manifest_digest_mismatch")

    def test_approved_file_sizes_and_sha_are_checked_independently(self):
        for index in (0, 1):
            packet, _ = packet_fixture(); packet["asset"]["files"][index]["size_bytes"] += 1
            self.assert_rejected(sign_manifest(packet), "asset_size_mismatch")
            packet, _ = packet_fixture(); packet["asset"]["files"][index]["sha256"] = "0" * 64
            self.assert_rejected(sign_manifest(packet), "blob_digest_mismatch")
        packet, _ = packet_fixture(); packet["input_sha256"] = "0" * 64
        self.assert_rejected(packet, "blob_digest_mismatch")

    def test_missing_model_or_config_manifest_record_is_rejected(self):
        for index in (0, 1):
            packet, _ = packet_fixture(); packet["asset"]["files"].pop(index)
            self.assert_rejected(sign_manifest(packet), "unsupported_asset_file")

    def test_manifest_paths_are_whitelisted_even_with_valid_recomputed_digest(self):
        for name in ("sample", "../extra.py", "/work/code.py", "model.onnx.data", "readme.md", None, 1):
            packet, _ = packet_fixture()
            packet["asset"]["files"].append({"relative_path": name, "size_bytes": 1, "sha256": sha(b"x")})
            with self.subTest(name=name):
                self.assert_rejected(sign_manifest(packet), "unsupported_asset_file")

    def test_manifest_records_require_positive_integer_sizes_and_complete_hashes(self):
        for field, values in (("size_bytes", (None, True, False, 0, -1, 1.5, "19")), ("sha256", (None, 1, "", "A" * 64, "a" * 63))):
            for value in values:
                packet, _ = packet_fixture(); packet["asset"]["files"][0][field] = value
                with self.subTest(field=field, value=value):
                    self.assert_rejected(sign_manifest(packet), "invalid_manifest_record")

    def test_duplicate_json_keys_are_rejected_at_every_level(self):
        packet, _ = packet_fixture()
        raw = encode(packet)
        variants = (
            raw.replace(b'"task_id":"task-test"', b'"task_id":"other","task_id":"task-test"'),
            raw.replace(b'"size_bytes":20', b'"size_bytes":1,"size_bytes":20'),
            raw.replace(b'"blobs":{', b'"blobs":{"sample":"eA==",'),
        )
        for value in variants:
            with self.subTest(raw=value):
                self.assertNotEqual(value, raw, "duplicate-key fixture must actually differ")
                with self.assertRaisesRegex(ValueError, "duplicate_json_key"):
                    runner.validate_packet(value)

    def test_blob_encoding_and_nonempty_limits(self):
        for name in ("model.onnx", "config.json", "sample"):
            for value, code in ((None, "invalid_blob"), (1, "invalid_blob"), ("", "blob_size_limit")):
                packet, _ = packet_fixture(); packet["blobs"][name] = value
                self.assert_rejected(packet, code)
            for value in ("%%%", "a", " eA==", "eA==\n"):
                packet, _ = packet_fixture(); packet["blobs"][name] = value
                with self.assertRaises(ValueError):
                    runner.validate_packet(encode(packet))

    def test_model_config_and_sample_have_independent_bounded_sizes(self):
        for name, limit in (("model.onnx", 16 * 1024 * 1024), ("config.json", 1024 * 1024), ("sample", runner.MAX_INPUT_BYTES)):
            packet, _ = packet_fixture(); packet["blobs"][name] = base64.b64encode(b"x" * (limit + 1)).decode()
            with self.subTest(name=name):
                self.assert_rejected(packet, "blob_size_limit")

    def test_host_guard_runs_before_stdin_and_any_native_runtime_import(self):
        stdin = Mock(); stderr = io.StringIO()
        with patch.object(runner.sys, "platform", "darwin"), patch.object(runner.sys, "stdin", stdin), redirect_stderr(stderr), patch("builtins.__import__") as imports:
            self.assertEqual(runner.main(), 1)
        stdin.buffer.read.assert_not_called()
        forbidden = {"onnxruntime", "numpy", "PIL", "model_harness.model_assets", "model_harness.huggingface_assets", "model_harness.onnx_image_features"}
        self.assertFalse(any(call.args[0] in forbidden for call in imports.call_args_list))
        result = json.loads(stderr.getvalue())
        self.assertEqual(result, {"schema_version": "1.0", "status": "failed", "error_code": "ValueError"})
        self.assertNotIn("training", result)

    def test_container_guard_requires_exact_unprivileged_uid_and_gid(self):
        with guard_facts():
            runner._container_guard()
        for facts in ({"uid": 0}, {"gid": 0}, {"uid": 1000}, {"gid": 1000}):
            with self.subTest(facts=facts), guard_facts(**facts), self.assertRaisesRegex(ValueError, "unprivileged_container_required"):
                runner._container_guard()

    def test_container_guard_rejects_missing_marker_or_any_non_loopback_network(self):
        with guard_facts(marker=False), self.assertRaisesRegex(ValueError, "linux_container_required"):
            runner._container_guard()
        for network in ((), ("eth0",), ("lo", "eth0")):
            with self.subTest(network=network), guard_facts(network=network), self.assertRaisesRegex(ValueError, "offline_container_required"):
                runner._container_guard()

    def test_container_guard_rejects_ambient_tokens_before_input_or_model_loading(self):
        for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "MODEL_HARNESS_AGENT_BRIDGE_TOKEN"):
            with self.subTest(name=name), guard_facts(env={name: "test-sentinel-not-a-real-secret"}), self.assertRaisesRegex(ValueError, "ambient_credentials_rejected"):
                runner._container_guard()

    def test_real_host_entrypoint_exits_nonzero_without_onnx_import(self):
        script = (
            "import runpy, sys\n"
            "try:\n"
            f"    runpy.run_path({str(RUNNER_PATH)!r}, run_name='__main__')\n"
            "except SystemExit as exc:\n"
            "    assert exc.code != 0\n"
            "    assert not any(name == 'onnxruntime' or name.startswith('onnxruntime.') for name in sys.modules)\n"
            "    raise\n"
        )
        completed = subprocess.run([sys.executable, "-S", "-c", script], input=b"", capture_output=True, timeout=10, check=False)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, b"")
        self.assertEqual(json.loads(completed.stderr), {"schema_version": "1.0", "status": "failed", "error_code": "ValueError"})


if __name__ == "__main__":
    unittest.main()
