"""Mock-only probe boundary tests, not evidence of model or container execution.

The fixed probe is imported without executing main. No test downloads files,
loads an ONNX runtime, starts a container, or imports third-party model code.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch


PROBE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "probe_hf_onnx_cpu.py"
SPEC = importlib.util.spec_from_file_location("fixed_hf_onnx_cpu_probe_tests", PROBE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


@contextmanager
def isolated_boundary(*, platform="linux", marker=True, uid=1000, euid=1000,
                      interfaces=("lo",), env=None, symlink=False, directory=True,
                      resolved_path=None):
    """Simulate guard facts only; never provision a real host /probe directory."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(probe.sys, "platform", platform))
        stack.enter_context(patch.object(probe.os, "getuid", return_value=uid))
        stack.enter_context(patch.object(probe.os, "geteuid", return_value=euid))
        stack.enter_context(patch.dict(probe.os.environ, env or {}, clear=True))
        stack.enter_context(patch.object(Path, "is_file", return_value=marker))
        stack.enter_context(patch.object(Path, "is_dir", return_value=directory))
        stack.enter_context(patch.object(
            Path, "is_symlink", autospec=True,
            side_effect=lambda path: symlink(path) if callable(symlink) else symlink,
        ))
        stack.enter_context(patch.object(
            Path, "resolve", autospec=True,
            side_effect=lambda path: Path(resolved_path) if resolved_path else path,
        ))
        stack.enter_context(patch.object(
            Path, "iterdir", autospec=True,
            side_effect=lambda _path: iter(Path("/sys/class/net") / name for name in interfaces),
        ))
        yield


class ProbeBoundaryTests(unittest.TestCase):
    def test_fixed_source_is_immutable_and_file_selection_is_narrow(self):
        self.assertEqual(probe.REPO_ID, "pyronear/mobilenet_v3_small")
        self.assertEqual(probe.COMMIT, "a6a0b39ca1f5b0a247eb0a2e83f06cd95fc03674")
        self.assertEqual(probe.MODEL_SHA256, "8fd451f919499e30e879eda19bfd2b249ceec77e4f1c02f7b022730e365ae897")
        self.assertEqual(probe.MODEL_BYTES, 6_068_953)
        self.assertEqual(probe.FILES, ("README.md", "config.json", "model.onnx"))
        self.assertEqual(probe.EXPECTED_LICENSE, "apache-2.0")

    def test_only_the_two_provisioned_container_workspaces_are_allowed(self):
        for workspace in ("/probe", "/tmp/probe"):
            with self.subTest(workspace=workspace), isolated_boundary():
                root, facts = probe._boundary("infer", workspace)
                self.assertEqual(root, Path(workspace))
                self.assertTrue(facts["offline_execution"])
                self.assertEqual(facts["network_interfaces"], ["lo"])
                self.assertEqual(probe.os.environ["HF_HUB_OFFLINE"], "1")
                self.assertEqual(probe.os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"], "1")
                self.assertEqual(probe.os.environ["HF_HUB_DISABLE_TELEMETRY"], "1")
                self.assertEqual(probe.os.environ["ORT_DISABLE_TELEMETRY"], "1")

    def test_prepare_may_have_network_but_never_implicit_credentials(self):
        with isolated_boundary(interfaces=("eth0", "lo")):
            _, facts = probe._boundary("prepare", "/probe")
            self.assertFalse(facts["offline_execution"])
            self.assertEqual(probe.os.environ["HF_HUB_OFFLINE"], "0")
            self.assertEqual(probe.os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"], "1")

    def test_host_platforms_and_missing_or_symlinked_marker_fail_closed(self):
        cases = [
            ({"platform": "darwin"}, "linux_container_required"),
            ({"platform": "win32"}, "linux_container_required"),
            ({"marker": False}, "docker_container_marker_required"),
            ({"symlink": True}, "docker_container_marker_required"),
        ]
        for facts, reason in cases:
            with self.subTest(facts=facts), isolated_boundary(**facts):
                with self.assertRaisesRegex(probe.ProbeError, reason):
                    probe._boundary("prepare", "/probe")

    def test_real_or_effective_root_is_rejected(self):
        for uid, euid in ((0, 1000), (1000, 0), (0, 0)):
            with self.subTest(uid=uid, euid=euid), isolated_boundary(uid=uid, euid=euid):
                with self.assertRaisesRegex(probe.ProbeError, "non_root_user_required"):
                    probe._boundary("infer", "/probe")

    def test_inference_requires_exactly_loopback_only(self):
        for interfaces in ((), ("eth0",), ("eth0", "lo"), ("lo", "tun0")):
            with self.subTest(interfaces=interfaces), isolated_boundary(interfaces=interfaces):
                with self.assertRaisesRegex(probe.ProbeError, "inference_requires_only_loopback_network"):
                    probe._boundary("infer", "/probe")

    def test_all_supported_token_environment_spellings_are_rejected(self):
        for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_HUB_TOKEN"):
            for command in ("prepare", "infer"):
                with self.subTest(key=key, command=command), isolated_boundary(env={key: "test-secret"}):
                    with self.assertRaisesRegex(probe.ProbeError, "credential_environment_not_allowed"):
                        probe._boundary(command, "/probe")

    def test_non_official_endpoint_is_rejected(self):
        for endpoint in ("https://mirror.invalid", "http://huggingface.co", "https://huggingface.co.attacker.invalid", ""):
            with self.subTest(endpoint=endpoint), isolated_boundary(env={"HF_ENDPOINT": endpoint}):
                with self.assertRaisesRegex(probe.ProbeError, "only_official_public_huggingface_endpoint_allowed"):
                    probe._boundary("prepare", "/probe")

    def test_arbitrary_host_and_nested_workspaces_are_rejected(self):
        for workspace in ("/", "/tmp", "/tmp/probe-other", "/probe/child", "/probe/../other", "probe", "/Users/test/project"):
            with self.subTest(workspace=workspace), isolated_boundary():
                with self.assertRaisesRegex(probe.ProbeError, "workspace_must_be_container_private_probe"):
                    probe._boundary("prepare", workspace)
        with isolated_boundary(resolved_path="/private/host-data"):
            with self.assertRaisesRegex(probe.ProbeError, "unsafe_workspace_path"):
                probe._boundary("infer", "/tmp/probe")
        with isolated_boundary(symlink=lambda path: path == Path("/probe")):
            with self.assertRaisesRegex(probe.ProbeError, "unsafe_workspace_path"):
                probe._boundary("infer", "/probe")
        with isolated_boundary(directory=False):
            with self.assertRaisesRegex(probe.ProbeError, "caller_must_provision_probe_directory"):
                probe._boundary("prepare", "/probe")

    def test_main_host_failure_never_calls_prepare_or_infer(self):
        for command in ("prepare", "infer"):
            output = io.StringIO()
            with self.subTest(command=command), isolated_boundary(platform="darwin"), \
                    patch.object(probe, "prepare") as prepare, patch.object(probe, "infer") as infer, \
                    redirect_stdout(output):
                result = probe.main([command])
            self.assertEqual(result, 1)
            prepare.assert_not_called()
            infer.assert_not_called()
            report = json.loads(output.getvalue())
            self.assertEqual(report["status"], "failure")
            self.assertEqual(report["reason"], "linux_container_required")
            for key in ("training_run_created", "release_gates_modified", "business_quality_accepted", "product_dynamic_execution_validated"):
                self.assertIs(report[key], False)
            self.assertNotIn("checks", report)

    def test_main_argument_errors_are_failure_json_before_any_execution(self):
        for arguments in ([], ["train"], ["infer", "--repo", "unapproved/repository"]):
            output = io.StringIO()
            with self.subTest(arguments=arguments), patch.object(probe, "_boundary") as boundary, \
                    patch.object(probe, "prepare") as prepare, patch.object(probe, "infer") as infer, redirect_stdout(output):
                self.assertEqual(probe.main(arguments), 1)
            boundary.assert_not_called()
            prepare.assert_not_called()
            infer.assert_not_called()
            report = json.loads(output.getvalue())
            self.assertEqual(report["status"], "failure")
            self.assertTrue(report["reason"].startswith("invalid_arguments:"))
            self.assertFalse(report["training_run_created"])
            self.assertFalse(report["business_quality_accepted"])

    def test_dependency_failure_is_sanitized_and_never_claims_acceptance(self):
        output = io.StringIO()
        with patch.object(probe, "_boundary", return_value=(Path("/probe"), {})), \
                patch.object(probe.sys, "path", list(sys.path)), \
                patch.object(probe, "prepare", side_effect=RuntimeError("private-token-sentinel")), \
                patch.object(probe, "infer") as infer, redirect_stdout(output):
            self.assertEqual(probe.main(["prepare"]), 1)
        infer.assert_not_called()
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "failure")
        self.assertEqual(report["reason"], "dependency_or_execution_failed")
        self.assertNotIn("private-token-sentinel", output.getvalue())
        self.assertFalse(report["training_run_created"])
        self.assertFalse(report["business_quality_accepted"])
        self.assertFalse(report["product_dynamic_execution_validated"])


class ProbeAnonymousDownloaderTests(unittest.TestCase):
    @contextmanager
    def downloader(self, siblings=None):
        metadata = SimpleNamespace(siblings=siblings if siblings is not None else [
            SimpleNamespace(rfilename=name, size=probe.MODEL_BYTES if name == "model.onnx" else 256)
            for name in probe.FILES
        ])
        api = Mock()
        api.model_info.return_value = metadata
        hf_module = ModuleType("huggingface_hub")
        hf_module.HfApi = Mock(return_value=api)
        hf_module.snapshot_download = Mock(return_value="/mock/no-files-downloaded")
        assets_module = ModuleType("model_harness.huggingface_assets")
        assets_module.HuggingFaceHubDownloader = Mock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
        with patch.dict(sys.modules, {
            "huggingface_hub": hf_module,
            "model_harness.huggingface_assets": assets_module,
        }):
            yield probe._anonymous_downloader(), hf_module, assets_module, api

    def test_official_calls_force_token_false_through_public_injection(self):
        with self.downloader() as (downloader, hf, assets, api):
            kwargs = assets.HuggingFaceHubDownloader.call_args.kwargs
            self.assertEqual(set(kwargs), {"api_factory", "snapshot_download_fn"})
            anonymous = downloader.api_factory(token="must-not-be-forwarded")
            hf.HfApi.assert_called_once_with(token=False)
            anonymous.model_info(repo_id=probe.REPO_ID, revision=probe.COMMIT, files_metadata=True, token="must-not-be-forwarded")
            self.assertIs(api.model_info.call_args.kwargs["token"], False)
            self.assertEqual(api.model_info.call_args.kwargs["revision"], probe.COMMIT)
            downloader.snapshot_download_fn(repo_id=probe.REPO_ID, revision=probe.COMMIT, allow_patterns=probe.FILES, token="must-not-be-forwarded")
            self.assertIs(hf.snapshot_download.call_args.kwargs["token"], False)
            self.assertEqual(hf.snapshot_download.call_args.kwargs["allow_patterns"], probe.FILES)

    def test_missing_or_unbounded_metadata_never_reaches_snapshot(self):
        valid = [SimpleNamespace(rfilename=name, size=probe.MODEL_BYTES if name == "model.onnx" else 256) for name in probe.FILES]
        cases = [(valid[:-1], "required_fixed_model_files_missing")]
        for size in (None, 0, -1, probe.MAX_FILE_BYTES + 1):
            cases.append(([SimpleNamespace(rfilename="README.md", size=size), *valid[1:]], "model_metadata_size_missing_or_over_budget"))
        cases.append(([valid[0], valid[1], SimpleNamespace(rfilename="model.onnx", size=probe.MODEL_BYTES - 1)], "fixed_model_metadata_size_mismatch"))
        cases.append(([SimpleNamespace(rfilename=name, size=3_000_000 if name != "model.onnx" else probe.MODEL_BYTES) for name in probe.FILES], "model_metadata_total_over_budget"))
        for siblings, reason in cases:
            with self.subTest(reason=reason), self.downloader(siblings) as (downloader, hf, _assets, _api):
                with self.assertRaisesRegex(probe.ProbeError, reason):
                    downloader.api_factory().model_info(repo_id=probe.REPO_ID, revision=probe.COMMIT)
                hf.snapshot_download.assert_not_called()


class ProbePinnedAssetTests(unittest.TestCase):
    def test_wrong_source_commit_or_model_hash_is_rejected_before_resolve(self):
        for field, value, reason in (
            ("repo_id", "other/model", "unexpected_model_source"),
            ("requested_revision", "main", "unexpected_model_commit"),
            ("resolved_commit", "0" * 40, "unexpected_model_commit"),
            ("model_sha256", "a" * 64, "fixed_model_sha256_mismatch"),
        ):
            with self.subTest(field=field):
                hashes = {name: probe.MODEL_SHA256 if name == "model.onnx" else "b" * 64 for name in probe.FILES}
                if field == "model_sha256":
                    hashes["model.onnx"] = value
                asset = SimpleNamespace(
                    provider="huggingface", repo_id=probe.REPO_ID, requested_revision=probe.COMMIT,
                    resolved_commit=probe.COMMIT, status="active", security_status="verified",
                    license=probe.EXPECTED_LICENSE, asset_id="mock-asset",
                    files=[SimpleNamespace(relative_path=name, size_bytes=probe.MODEL_BYTES if name == "model.onnx" else 256, sha256=hashes[name]) for name in probe.FILES],
                )
                if field != "model_sha256":
                    setattr(asset, field, value)
                paths = {}
                for record in asset.files:
                    path = MagicMock(spec=Path)
                    path.name = record.relative_path
                    path.is_file.return_value = True
                    path.is_symlink.return_value = False
                    path.stat.return_value = SimpleNamespace(st_size=record.size_bytes)
                    paths[record.relative_path] = path
                root = MagicMock(spec=Path)
                root.is_symlink.return_value = False
                root.iterdir.return_value = list(paths.values())
                root.__truediv__.side_effect = paths.__getitem__
                store = Mock()
                store.asset_files_dir.return_value = root
                module = ModuleType("model_harness.huggingface_assets")
                module.resolve_training_asset = Mock()
                with patch.dict(sys.modules, {"model_harness.huggingface_assets": module}), \
                        patch.object(probe, "_file_sha256", side_effect=lambda path: hashes[path.name]):
                    with self.assertRaisesRegex(probe.ProbeError, reason):
                        probe._check_asset(asset, store)
                module.resolve_training_asset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
