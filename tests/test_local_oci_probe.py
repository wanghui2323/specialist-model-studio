from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import verify_local_oci as probe


TOKEN = "a" * 32
CONTAINER_ID = "b" * 64
IMAGE_ID = "sha256:" + "c" * 64
IMAGE = "alpine@sha256:" + "d" * 64
NAME = f"studio-oci-probe-{TOKEN}"
OBSERVATIONS = """uid=65534
rootfs_write_denied=1
host_home_visible=0
interfaces=lo
ipv4_external_routes=0
ipv6_external_routes=0
cap_eff=0000000000000000
no_new_privs=1
tmpfs_write=1
tmpfs_type=tmpfs
cgroup_version=2
cpu_quota=100000
cpu_period=100000
memory_bytes=134217728
pids=32
"""


class FakeDocker:
    def __init__(self, *, timeout_at=None, drift=None, wrong_owner=False, observations=OBSERVATIONS,
                 image_missing=False, image_mismatch=False, cleanup_failure=False,
                 server_os="linux", server_arch="arm64", image_os="linux", image_arch="arm64"):
        self.calls = []
        self.exists = False
        self.running = False
        self.timeout_at = timeout_at
        self.drift = drift or {}
        self.wrong_owner = wrong_owner
        self.observations = observations
        self.image_missing = image_missing
        self.image_mismatch = image_mismatch
        self.cleanup_failure = cleanup_failure
        self.server_os, self.server_arch = server_os, server_arch
        self.image_os, self.image_arch = image_os, image_arch

    def container(self):
        return {"Id": CONTAINER_ID, "Name": f"/{NAME}", "Image": IMAGE_ID,
                "Config": {"User": "65534:65534", "Labels": {probe.LABEL: "other" if self.wrong_owner else TOKEN}},
                "HostConfig": {"NetworkMode": "none", "NanoCpus": 1_000_000_000, "Memory": 134_217_728,
                               "MemorySwap": 134_217_728, "PidsLimit": 32, "ReadonlyRootfs": True,
                               "Privileged": False, "CgroupnsMode": "private", "IpcMode": "private", "CapDrop": ["ALL"],
                               "SecurityOpt": ["no-new-privileges"], "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=16m,mode=1777"}, **self.drift},
                "Mounts": [], "State": {"Running": self.running}}

    def __call__(self, command, **kwargs):
        args = command[command.index("-H") + 2:]
        self.calls.append((command, args, kwargs))
        output, error, code = "", "", 0
        if args[0] == "version":
            output = json.dumps({"Version": "test-server", "Os": self.server_os, "Arch": self.server_arch})
        elif args[:2] == ["image", "inspect"]:
            if self.image_missing:
                code, error = 1, "No such image"
            else:
                output = json.dumps([{"Id": IMAGE_ID, "RepoDigests": ["alpine@sha256:" + "e" * 64] if self.image_mismatch else [IMAGE],
                                      "Os": self.image_os, "Architecture": self.image_arch, "Config": {}}])
        elif args[:2] == ["container", "create"]:
            self.exists = True
            if self.timeout_at == "create":
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            output = CONTAINER_ID + "\n"
        elif args[:2] == ["container", "inspect"]:
            if self.exists:
                output = json.dumps([self.container()])
            else:
                code, error = 1, f"Error: No such container: {args[2]}"
        elif args[:2] == ["container", "start"]:
            self.running = True
            output = CONTAINER_ID
        elif args[:2] == ["container", "exec"]:
            if self.timeout_at == "exec":
                raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"partial")
            output = self.observations
        elif args[:2] == ["container", "stop"]:
            self.running = False
            output = CONTAINER_ID
        elif args[:2] == ["container", "rm"]:
            if self.cleanup_failure:
                code, error = 1, "daemon unavailable"
            else:
                self.exists = False
                output = CONTAINER_ID
        else:
            raise AssertionError(f"Unexpected Docker command: {args}")
        return subprocess.CompletedProcess(command, code, output, error)


class LocalOCIProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.socket = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.socket.close)
        self.socket_path = self.root / "docker.sock"
        self.socket.bind(str(self.socket_path))
        self.argv = ["--docker-binary", str(Path(sys.executable).absolute()), "--endpoint", f"unix://{self.socket_path}",
                     "--image", IMAGE, "--output", str(self.root / "evidence.json")]

    def run_fake(self, fake):
        args = probe.parse_args(self.argv)
        with patch.object(probe.subprocess, "run", side_effect=fake), patch.object(probe.uuid, "uuid4", return_value=SimpleNamespace(hex=TOKEN)):
            return probe.run_probe(args)

    def reject(self, argv):
        with patch.object(probe.subprocess, "run") as command, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                probe.parse_args(argv)
            self.assertEqual(raised.exception.code, 2)
            command.assert_not_called()

    def test_required_parameters_and_unsafe_endpoints_are_rejected_before_docker(self):
        self.reject([])
        for endpoint in ["tcp://127.0.0.1:2375", "tcp://remote:2376", "ssh://host", "unix://relative",
                         "unix://remote/path", "unix:///missing/socket", f"unix://{self.socket_path}?context=remote",
                         f"unix://{self.socket_path}#remote", "unix:///%2Ftmp/docker.sock"]:
            with self.subTest(endpoint=endpoint):
                argv = list(self.argv)
                argv[3] = endpoint
                self.reject(argv)

    def test_only_absolute_executable_and_official_fixed_alpine_digest_are_accepted(self):
        for binary in ["docker", str(self.root), str(self.root / "missing")]:
            argv = list(self.argv)
            argv[1] = binary
            self.reject(argv)
        for image in ["alpine", "alpine:latest", "alpine:3.21", "sha256:" + "d" * 64,
                      "user/alpine@sha256:" + "d" * 64, "alpine@sha256:123", IMAGE.upper(), "--privileged"]:
            with self.subTest(image=image):
                argv = list(self.argv)
                argv[5] = image
                self.reject(argv)
        for prefix in ["", "library/", "docker.io/library/"]:
            argv = list(self.argv)
            argv[5] = prefix + IMAGE
            self.assertEqual(probe.parse_args(argv).image, prefix + IMAGE)

    def test_prior_evidence_is_not_overwritten(self):
        output = Path(self.argv[-1])
        output.write_text("prior evidence", encoding="utf-8")
        self.reject(self.argv)
        self.assertEqual(output.read_text(encoding="utf-8"), "prior evidence")

    def test_every_command_pins_local_endpoint_empty_config_and_isolation_flags(self):
        fake = FakeDocker()
        with patch.dict(os.environ, {"DOCKER_CONTEXT": "remote", "DOCKER_HOST": "ssh://remote", "DOCKER_TLS_VERIFY": "1", "HTTP_PROXY": "http://remote", "DOCKER_API_VERSION": "old"}):
            report = self.run_fake(fake)
        self.assertEqual(report["status"], "passed", report["errors"])
        self.assertEqual(report["evidence_type"], "LocalOCIProbeEvidence")
        self.assertEqual(report["cleanup"]["status"], "removed")
        self.assertFalse(report["stopped_container"]["State"]["Running"])
        for command, args, kwargs in fake.calls:
            self.assertEqual(command[0], self.argv[1])
            self.assertEqual(command[1], "--config")
            self.assertEqual(command[3:5], ["-H", self.argv[3]])
            self.assertEqual(kwargs["env"]["DOCKER_CONFIG"], command[2])
            self.assertNotIn("HOME", kwargs["env"], "host HOME is neither inherited nor repurposed")
            self.assertEqual(kwargs["env"]["DOCKER_HOST"], self.argv[3])
            self.assertEqual(set(kwargs["env"]), {"PATH", "DOCKER_CONFIG", "DOCKER_HOST", "LC_ALL"})
            self.assertLessEqual(kwargs["timeout"], 20)
            self.assertNotIn("shell", kwargs)
            self.assertNotIn("pull", args)
            self.assertFalse(Path(command[2]).exists(), "isolated client config is removed after the probe")
        create = next(args for _, args, _ in fake.calls if args[:2] == ["container", "create"])
        for flag, value in {"--name": NAME, "--label": f"{probe.LABEL}={TOKEN}", "--cpus": "1", "--memory": "128m",
                            "--memory-swap": "128m", "--pids-limit": "32", "--network": "none", "--user": "65534:65534",
                            "--cap-drop": "ALL", "--security-opt": "no-new-privileges", "--ipc": "private", "--cgroupns": "private",
                            "--tmpfs": "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777", "--entrypoint": "/bin/sh"}.items():
            self.assertEqual(create[create.index(flag) + 1], value)
        self.assertIn("--read-only", create)
        self.assertIn("--pull=never", create)
        self.assertEqual(create[-3:], [IMAGE, "-c", "exec sleep 300"])
        for prohibited in ["--volume", "-v", "--mount", "--privileged", "--gpus", "--device", "--publish"]:
            self.assertNotIn(prohibited, create)
        execution = next(args for _, args, _ in fake.calls if args[:2] == ["container", "exec"])
        self.assertEqual(execution[2:], [CONTAINER_ID, "/bin/sh", "-eu", "-c", probe.PROBE_SCRIPT])
        self.assertNotIn("curl", probe.PROBE_SCRIPT)
        self.assertNotIn("wget", probe.PROBE_SCRIPT)
        self.assertNotIn("ping", probe.PROBE_SCRIPT)

    def test_create_or_execution_timeout_attempts_exact_owned_cleanup_and_never_passes(self):
        for stage in ["create", "exec"]:
            with self.subTest(stage=stage):
                fake = FakeDocker(timeout_at=stage)
                report = self.run_fake(fake)
                self.assertEqual(report["status"], "failed")
                self.assertTrue(any("timed out" in error for error in report["errors"]))
                self.assertEqual(report["cleanup"]["status"], "removed")
                self.assertFalse(fake.exists)
                for _, args, _ in fake.calls:
                    if args[:2] in (["container", "stop"], ["container", "rm"]):
                        self.assertEqual(args[-1], CONTAINER_ID)
                self.assertTrue(any(record.get("timed_out") for record in report["commands"]))

    def test_ownership_mismatch_never_starts_stops_or_deletes_other_container(self):
        fake = FakeDocker(wrong_owner=True)
        report = self.run_fake(fake)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["cleanup"]["status"], "unverified")
        self.assertTrue(fake.exists)
        self.assertFalse(any(args[:2] in (["container", "start"], ["container", "stop"], ["container", "rm"]) for _, args, _ in fake.calls))

    def test_actual_configuration_drift_is_rejected_before_container_start(self):
        for drift in [{"NetworkMode": "host"}, {"ReadonlyRootfs": False}, {"NanoCpus": 0}, {"Memory": 0},
                      {"PidsLimit": -1}, {"Privileged": True}, {"SecurityOpt": []}, {"Binds": ["/home:/host"]},
                      {"DeviceRequests": [{"Capabilities": [["gpu"]]}]}, {"CapAdd": ["SYS_ADMIN"]}]:
            with self.subTest(drift=drift):
                fake = FakeDocker(drift=drift)
                report = self.run_fake(fake)
                self.assertEqual(report["status"], "failed")
                self.assertFalse(any(args[:2] == ["container", "start"] for _, args, _ in fake.calls))
                self.assertEqual(report["cleanup"]["status"], "removed")

    def test_missing_or_different_local_image_never_pulls_or_creates(self):
        for fake in [FakeDocker(image_missing=True), FakeDocker(image_mismatch=True)]:
            report = self.run_fake(fake)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["cleanup"]["status"], "not_created")
            self.assertFalse(any(args[0] == "container" or "pull" in args for _, args, _ in fake.calls))

    def test_linux_and_exact_cpu_architecture_identity_are_required_without_fallback(self):
        for identity in [{"server_os": "windows"}, {"server_os": None}, {"server_arch": None}, {"server_arch": ""},
                         {"image_os": "windows"}, {"image_os": None}, {"image_arch": "amd64"}, {"image_arch": None}]:
            with self.subTest(identity=identity):
                fake = FakeDocker(**identity)
                report = self.run_fake(fake)
                self.assertEqual(report["status"], "failed")
                self.assertTrue(report["errors"])
                self.assertEqual(report["cleanup"]["status"], "not_created")
                self.assertFalse(any(args[0] == "container" for _, args, _ in fake.calls))
        report = self.run_fake(FakeDocker(server_arch="amd64", image_arch="amd64"))
        self.assertEqual(report["status"], "passed", report["errors"])

    def test_failed_or_missing_negative_test_never_produces_success(self):
        for before, after in [("rootfs_write_denied=1", "rootfs_write_denied=0"), ("host_home_visible=0", "host_home_visible=1"),
                              ("interfaces=lo", "interfaces=eth0,lo"), ("ipv4_external_routes=0", "ipv4_external_routes=1"),
                              ("ipv6_external_routes=0", "ipv6_external_routes=1"), ("cpu_quota=100000", "cpu_quota=max"),
                              ("memory_bytes=134217728", "memory_bytes=268435456"), ("pids=32", "pids=64"),
                              ("no_new_privs=1", ""), ("cap_eff=0000000000000000", "cap_eff=0000000000000001")]:
            with self.subTest(before=before):
                report = self.run_fake(FakeDocker(observations=OBSERVATIONS.replace(before, after)))
                self.assertEqual(report["status"], "failed")
                self.assertTrue(report["errors"])
                self.assertEqual(report["cleanup"]["status"], "removed")

    def test_cleanup_failure_invalidates_otherwise_successful_probe(self):
        report = self.run_fake(FakeDocker(cleanup_failure=True))
        self.assertTrue(report["probe_checks_passed"])
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["cleanup"]["status"], "unverified")

    def test_cli_writes_failed_evidence_and_nonzero_exit_without_fake_run_objects(self):
        fake = FakeDocker(timeout_at="exec")
        with patch.object(probe.subprocess, "run", side_effect=fake), patch.object(probe.uuid, "uuid4", return_value=SimpleNamespace(hex=TOKEN)), contextlib.redirect_stdout(io.StringIO()):
            code = probe.main(self.argv)
        evidence = json.loads(Path(self.argv[-1]).read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertEqual(evidence["status"], "failed")
        self.assertFalse(any(key in evidence for key in ["task_id", "run_id", "model_trial_id", "qualification_run_id"]))
        self.assertEqual(Path(self.argv[-1]).stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
