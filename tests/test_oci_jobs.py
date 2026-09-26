from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from model_harness import oci_jobs as jobs


IMAGE = "sha256:" + "a" * 64
CONTAINER = "b" * 64
TASK, JOB = "task-1", "trial-1"


class FakeRuntime:
    def __init__(self, executor, *, flags=None, interruption=None, cleanup_unavailable=False,
                 stop_ineffective=False, stop_timeout=False, remove_ineffective=False,
                 create_timeout=False, server_os="linux", image_arch="arm64", image_id=IMAGE):
        self.executor = executor
        self.calls = []
        self.exists, self.running, self.exit_code = False, False, 0
        self.name, self.labels = executor._identity(JOB, TASK)
        self.flags = flags or {}
        self.interruption = interruption
        self.cleanup_unavailable = cleanup_unavailable
        self.stop_ineffective, self.stop_timeout = stop_ineffective, stop_timeout
        self.remove_ineffective, self.create_timeout = remove_ineffective, create_timeout
        self.server_os, self.image_arch, self.image_id = server_os, image_arch, image_id
        self.attached = False
        self.payload = None

    def container(self):
        config = self.executor.config
        return {
            "Id": CONTAINER, "Name": "/" + self.name, "Image": IMAGE,
            "Config": {"User": "65534:65534", "Labels": dict(self.labels), "Tty": False,
                       "OpenStdin": True, "WorkingDir": "/work", "Entrypoint": [config.command[0]],
                       "Cmd": list(config.command[1:]), "Healthcheck": {"Test": ["NONE"]}},
            "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                           "NanoCpus": 1_000_000_000, "Memory": config.memory_bytes,
                           "MemorySwap": config.memory_bytes, "PidsLimit": config.pids_limit,
                           "IpcMode": "private", "CgroupnsMode": "private", "AutoRemove": False,
                           "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges"],
                           "Tmpfs": {"/work": jobs._TMPFS}, "RestartPolicy": {"Name": "no"},
                           "LogConfig": {"Type": "local", "Config": {"max-size": "1m", "max-file": "1", "compress": "false"}},
                           **self.flags},
            "Mounts": [], "State": {"Running": self.running, "ExitCode": self.exit_code},
        }

    def __call__(self, args, client_dir, deadline, **kwargs):
        self.calls.append((list(args), kwargs))
        if args[0] == "version":
            value = {"Os": self.server_os, "Arch": "arm64"}
        elif args[:2] == ["image", "inspect"]:
            value = [{"Id": self.image_id, "Os": "linux", "Architecture": self.image_arch,
                      "Config": {}, "RepoDigests": []}]
        elif args[:2] == ["container", "inspect"]:
            if self.cleanup_unavailable and self.attached:
                raise jobs._JobError("container_observation_unavailable")
            if not self.exists:
                return jobs._ProcessResult(1, stderr=f"Error: No such container: {args[2]}".encode())
            value = [self.container()]
        elif args[:2] == ["container", "create"]:
            self.exists = True
            self.name = args[args.index("--name") + 1]
            self.labels = dict(args[index + 1].split("=", 1) for index, arg in enumerate(args) if arg == "--label")
            if self.create_timeout:
                raise jobs._JobError("control_timed_out")
            return jobs._ProcessResult(0, (CONTAINER + "\n").encode())
        elif args[:2] == ["container", "start"]:
            self.running = True
            self.payload = kwargs["payload"]
            if kwargs.get("on_attached"):
                kwargs["on_attached"]()
            self.attached = True
            if not self.interruption:
                self.running = False
            return jobs._ProcessResult(0 if not self.interruption else -9, b'{"ok":true}', b"", self.interruption)
        elif args[:2] == ["container", "stop"]:
            if self.stop_timeout:
                raise jobs._JobError("control_timed_out")
            if not self.stop_ineffective:
                self.running, self.exit_code = False, 137
            return jobs._ProcessResult(0)
        elif args[:2] == ["container", "kill"]:
            self.running, self.exit_code = False, 137
            return jobs._ProcessResult(0)
        elif args[:2] == ["container", "rm"]:
            if not self.remove_ineffective:
                self.exists = False
            return jobs._ProcessResult(0)
        else:
            raise AssertionError(args)
        return jobs._ProcessResult(0, json.dumps(value).encode())


class OCIJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.socket = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.socket.close)
        self.socket_path = self.root / "runtime.sock"
        self.socket.bind(str(self.socket_path))
        self.config = jobs.OCIJobConfig(str(Path(sys.executable).absolute()), "unix://" + str(self.socket_path),
                                        IMAGE, jobs.TRIAL_COMMAND)
        self.executor = jobs.OCIJobExecutor(self.config)

    def execute(self, fake, *, cancel=None, on_started=None, payload=b"private job input"):
        with patch.object(self.executor, "_run", side_effect=fake):
            return self.executor.execute(job_id=JOB, task_id=TASK, payload=payload,
                                         cancel_event=cancel or threading.Event(), on_started=on_started)

    def recover(self, fake):
        with patch.object(self.executor, "_run", side_effect=fake):
            return self.executor.recover(JOB, TASK)

    def mutations(self, fake):
        return [args for args, _ in fake.calls if args[:2] in (
            ["container", "create"], ["container", "start"], ["container", "stop"],
            ["container", "kill"], ["container", "rm"],
        )]

    def test_config_rejects_remote_ambiguous_endpoint_and_mutable_image(self):
        for endpoint in ("tcp://localhost:2375", "ssh://host", "unix://host/tmp/a", "unix://relative",
                         "unix:///tmp/a?x=1", "unix:///tmp/a#x", "unix:///%2ftmp/a", "unix:///tmp/a\n"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                replace(self.config, endpoint=endpoint)
        for image in ("ubuntu", "ubuntu:latest", "--privileged", "sha256:abc", "a@sha256:" + "A" * 64):
            with self.subTest(image=image), self.assertRaises(ValueError):
                replace(self.config, image=image)
        for binary in ("docker", str(self.root), str(self.root / "missing")):
            with self.subTest(binary=binary), self.assertRaises(ValueError):
                replace(self.config, docker_binary=binary)
        for field, value in (("timeout_seconds", 0), ("pids_limit", True), ("memory_bytes", -1),
                             ("max_output_bytes", 0), ("command", ["python"])):
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(self.config, **{field: value})
        self.assertEqual(replace(self.config, image="repo/name@sha256:" + "d" * 64).image,
                         "repo/name@sha256:" + "d" * 64)

    def test_environment_requires_all_three_and_digest_omits_local_paths(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(jobs.from_environment())
        env = {"MODEL_HARNESS_OCI_DOCKER": self.config.docker_binary,
               "MODEL_HARNESS_OCI_ENDPOINT": self.config.endpoint, "MODEL_HARNESS_TRIAL_IMAGE": IMAGE}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(jobs.from_environment().command, jobs.TRIAL_COMMAND)
        second = replace(self.config, endpoint="unix:///missing/another.sock")
        self.assertEqual(second.runtime_digest, self.executor.runtime_digest)
        self.assertNotEqual(replace(self.config, timeout_seconds=31).runtime_digest, self.executor.runtime_digest)
        with patch.object(self.executor, "_run") as run:
            self.assertEqual(len(self.executor.runtime_digest), 64)
            run.assert_not_called()

    def test_client_argv_and_environment_never_inherit_credentials(self):
        with patch.dict(os.environ, {"HF_TOKEN": "secret", "DOCKER_HOST": "ssh://remote", "HOME": "/private/home"}):
            argv, env = self.executor._base("/private/client")
        self.assertEqual(argv, [self.config.docker_binary, "--config", "/private/client", "-H", self.config.endpoint])
        self.assertEqual(set(env), {"PATH", "DOCKER_CONFIG", "DOCKER_HOST", "LC_ALL"})
        self.assertNotIn("secret", repr(env))

    def test_control_commands_use_popen_no_shell_and_at_most_three_seconds(self):
        process = MagicMock()
        process.poll.return_value = 0
        process.returncode = 0
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.closed = True
        now = time.monotonic()
        with patch.object(jobs.subprocess, "Popen", return_value=process) as popen, patch.object(
            jobs, "_pump", return_value=jobs._ProcessResult(0)
        ) as pump:
            self.executor._run(["version"], "/private/client", now + 60)
        self.assertLessEqual(pump.call_args.kwargs["deadline"], now + 3.1)
        self.assertNotIn("shell", popen.call_args.kwargs)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertNotIn("HOME", popen.call_args.kwargs["env"])
        self.assertEqual(popen.call_args.args[0][-1], "version")

    def test_capability_checks_local_socket_linux_image_arch_digest_without_mutation(self):
        for kwargs, reason in (({}, "ready"), ({"server_os": "windows"}, "linux_server_required"),
                               ({"image_arch": "amd64"}, "image_architecture_mismatch"),
                               ({"image_id": "sha256:" + "c" * 64}, "image_digest_mismatch")):
            fake = FakeRuntime(self.executor, **kwargs)
            with self.subTest(reason=reason), patch.object(self.executor, "_run", side_effect=fake):
                report = self.executor.capability()
                self.assertEqual(report["reason"], reason)
                self.assertEqual(report["available"], reason == "ready")
                self.assertEqual(report["runtime_digest"], self.config.runtime_digest)
                self.assertEqual(self.mutations(fake), [])
        missing = jobs.OCIJobExecutor(replace(self.config, endpoint="unix:///nonexistent/studio.sock"))
        with patch.object(missing, "_run") as run:
            self.assertEqual(missing.capability()["reason"], "local_socket_unavailable")
            run.assert_not_called()

    def test_success_sends_stdin_only_and_verifies_all_flags_before_start(self):
        fake, phases = FakeRuntime(self.executor), []
        report = self.execute(fake, on_started=lambda evidence: phases.append(evidence["phase"]))
        self.assertEqual(report["status"], "succeeded", report)
        self.assertTrue(report["cleanup_confirmed"])
        self.assertEqual(report["exit_code"], 0)
        self.assertEqual(report["container_id"], CONTAINER)
        self.assertEqual(report["stdout"], '{"ok":true}')
        self.assertEqual(phases, ["created", "running"])
        self.assertEqual(fake.payload, b"private job input")
        create = next(args for args, _ in fake.calls if args[:2] == ["container", "create"])
        self.assertIn("--pull=never", create)
        self.assertIn("compress=false", create)
        self.assertNotIn("private job input", " ".join(create))
        self.assertEqual(create[create.index("--memory") + 1], create[create.index("--memory-swap") + 1])
        for forbidden in ("--mount", "-v", "--volume", "--publish", "--privileged", "--gpus", "--device"):
            self.assertNotIn(forbidden, create)
        for args in self.mutations(fake):
            if args[:2] != ["container", "create"]:
                self.assertEqual(args[-1], CONTAINER)
        self.assertFalse(fake.exists)
        self.assertIsNotNone(report["finished_at_utc"])

    def test_security_drift_never_starts_and_owned_container_is_removed(self):
        for flags in ({"NetworkMode": "host"}, {"Privileged": True}, {"MemorySwap": -1},
                      {"Binds": ["/private:/private"]}, {"CapAdd": ["SYS_ADMIN"]},
                      {"SecurityOpt": ["seccomp=unconfined"]}, {"Tmpfs": {}},
                      {"LogConfig": {"Type": "json-file"}}, {"UsernsMode": "host"}):
            with self.subTest(flags=flags):
                fake = FakeRuntime(self.executor, flags=flags)
                report = self.execute(fake)
                self.assertEqual(report["status"], "failed", report)
                self.assertTrue(report["cleanup_confirmed"])
                self.assertFalse(any(args[:2] == ["container", "start"] for args, _ in fake.calls))

    def test_cancellation_before_create_has_no_runtime_side_effect(self):
        event = threading.Event()
        event.set()
        fake = FakeRuntime(self.executor)
        report = self.execute(fake, cancel=event)
        self.assertEqual(report["status"], "cancelled")
        self.assertTrue(report["cleanup_confirmed"])
        self.assertEqual(fake.calls, [])

    def test_cancel_after_persisting_identity_prevents_start_and_cleans(self):
        event, fake = threading.Event(), FakeRuntime(self.executor)
        report = self.execute(fake, cancel=event, on_started=lambda _: event.set())
        self.assertEqual(report["status"], "cancelled")
        self.assertTrue(report["cleanup_confirmed"])
        self.assertFalse(fake.attached)

    def test_running_cancel_timeout_and_output_overflow_always_stop_and_verify(self):
        for interruption, status in (("cancelled", "cancelled"), ("timed_out", "timed_out"),
                                     ("output_limit_exceeded", "failed")):
            with self.subTest(interruption=interruption):
                fake = FakeRuntime(self.executor, interruption=interruption)
                report = self.execute(fake)
                self.assertEqual(report["status"], status, report)
                self.assertEqual(report["error_code"], interruption)
                self.assertTrue(report["cleanup_confirmed"])
                self.assertEqual(report["exit_code"], 137)
                self.assertTrue(any(args[:2] == ["container", "stop"] for args, _ in fake.calls))

    def test_stop_timeout_or_ineffective_stop_escalates_exact_id_to_kill(self):
        for kwargs in ({"stop_timeout": True}, {"stop_ineffective": True}):
            fake = FakeRuntime(self.executor, interruption="cancelled", **kwargs)
            report = self.execute(fake)
            self.assertEqual(report["status"], "cancelled", report)
            self.assertTrue(report["cleanup_confirmed"])
            self.assertIn(["container", "kill", CONTAINER], [args for args, _ in fake.calls])

    def test_daemon_loss_and_unconfirmed_removal_never_claim_cancelled_or_success(self):
        for kwargs in ({"cleanup_unavailable": True}, {"remove_ineffective": True}):
            fake = FakeRuntime(self.executor, interruption="cancelled", **kwargs)
            report = self.execute(fake)
            self.assertEqual(report["status"], "observation_degraded", report)
            self.assertFalse(report["cleanup_confirmed"])

    def test_uncertain_create_reconciles_nonce_and_does_not_leave_container(self):
        fake = FakeRuntime(self.executor, create_timeout=True)
        report = self.execute(fake)
        self.assertEqual(report["status"], "timed_out", report)
        self.assertTrue(report["cleanup_confirmed"])
        self.assertEqual(report["container_id"], CONTAINER)
        self.assertFalse(fake.exists)

    def test_uncertain_create_never_deletes_other_invocation_with_same_stable_labels(self):
        fake = FakeRuntime(self.executor, create_timeout=True)
        original = fake.__call__

        def other_invocation(args, *rest, **kwargs):
            try:
                return original(args, *rest, **kwargs)
            finally:
                if args[:2] == ["container", "create"]:
                    fake.labels[jobs._LABEL_PREFIX + "execution-id"] = "other-invocation"

        report = self.execute(other_invocation)
        self.assertEqual(report["status"], "observation_degraded")
        self.assertEqual(report["error_code"], "container_ownership_mismatch")
        self.assertTrue(fake.exists)
        self.assertFalse(any(args[:2] in (["container", "stop"], ["container", "rm"]) for args, _ in fake.calls))

    def test_existing_job_is_never_restarted_or_implicitly_removed(self):
        fake = FakeRuntime(self.executor)
        fake.exists = fake.running = True
        report = self.execute(fake)
        self.assertEqual(report["status"], "blocked_environment")
        self.assertFalse(report["cleanup_confirmed"])
        self.assertEqual(self.mutations(fake), [])

    def test_reentrancy_guard_and_recover_do_not_touch_live_local_job(self):
        name, _ = self.executor._identity(JOB, TASK)
        self.executor._active.add(name)
        fake = FakeRuntime(self.executor)
        report = self.execute(fake)
        self.assertEqual(report["error_code"], "job_already_executing")
        self.assertFalse(report["cleanup_confirmed"])
        report = self.recover(fake)
        self.assertEqual(report["status"], "observation_degraded")
        self.assertEqual(fake.calls, [])

    def test_recovery_exact_absence_and_owned_running_job_cancel_without_restart(self):
        for exists in (False, True):
            fake = FakeRuntime(self.executor)
            fake.exists = fake.running = exists
            report = self.recover(fake)
            self.assertEqual(report["status"], "cancelled", report)
            self.assertEqual(report["error_code"], "interrupted")
            self.assertTrue(report["cleanup_confirmed"])
            self.assertFalse(any(args[:2] in (["container", "create"], ["container", "start"]) for args, _ in fake.calls))

    def test_recovery_refuses_stale_digest_or_other_owner_without_mutation(self):
        for suffix in ("runtime-digest", "task-id", "job-id"):
            fake = FakeRuntime(self.executor)
            fake.exists = fake.running = True
            fake.labels[jobs._LABEL_PREFIX + suffix] = "wrong"
            report = self.recover(fake)
            self.assertEqual(report["status"], "observation_degraded")
            self.assertEqual(report["error_code"], "container_ownership_mismatch")
            self.assertFalse(report["cleanup_confirmed"])
            self.assertEqual(self.mutations(fake), [])

    def test_recovery_daemon_error_is_not_confused_with_exact_absence(self):
        with patch.object(self.executor, "_run", return_value=jobs._ProcessResult(
            1, stderr=b"Cannot connect to the Docker daemon"
        )):
            report = self.executor.recover(JOB, TASK)
        self.assertEqual(report["status"], "observation_degraded")
        self.assertFalse(report["cleanup_confirmed"])
        self.assertEqual(report["error_code"], "container_observation_unavailable")

    def test_real_docker_exact_missing_container_allows_only_empty_json_array(self):
        name, _ = self.executor._identity(JOB, TASK)
        for stdout in (b"", b"[]\n", b" [ ] \n"):
            with self.subTest(stdout=stdout), patch.object(self.executor, "_run", return_value=jobs._ProcessResult(
                1, stdout=stdout, stderr=f"Error response from daemon: No such container: {name}".encode()
            )):
                report = self.executor.recover(JOB, TASK)
                self.assertEqual(report["status"], "cancelled")
                self.assertTrue(report["cleanup_confirmed"])
        for stdout in (b"null", b"{}", b"[{}]", b"[] trailing"):
            with self.subTest(stdout=stdout), patch.object(self.executor, "_run", return_value=jobs._ProcessResult(
                1, stdout=stdout, stderr=f"Error response from daemon: No such container: {name}".encode()
            )):
                self.assertFalse(self.executor.recover(JOB, TASK)["cleanup_confirmed"])
        with patch.object(self.executor, "_run", return_value=jobs._ProcessResult(
            1, stdout=b"[]\n", stderr=b"Error response from daemon: No such container: other-container"
        )):
            self.assertFalse(self.executor.recover(JOB, TASK)["cleanup_confirmed"])

    def test_invalid_payload_does_not_invoke_runtime_or_return_input(self):
        fake = FakeRuntime(self.executor)
        report = self.execute(fake, payload=b"x" * (jobs.MAX_PAYLOAD_BYTES + 1))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error_code"], "invalid_or_oversized_payload")
        self.assertEqual(fake.calls, [])
        self.assertLess(len(json.dumps(report)), 1024)

    def test_callback_failure_cleans_created_container_and_never_starts(self):
        def broken(_):
            raise RuntimeError("secret callback data")
        fake = FakeRuntime(self.executor)
        report = self.execute(fake, on_started=broken)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["cleanup_confirmed"])
        self.assertNotIn("secret", json.dumps(report))
        self.assertFalse(fake.attached)


class PipePumpTests(unittest.TestCase):
    """Only run our own small stdlib Python snippets, never a runtime or model."""

    def spawn(self, code):
        return subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=0, close_fds=True)

    def test_simultaneous_stdout_stderr_and_large_stdin_do_not_deadlock(self):
        process = self.spawn("import sys; sys.stdout.buffer.write(b'o'*65536); sys.stdout.flush(); "
                             "sys.stderr.buffer.write(b'e'*65536); sys.stderr.flush(); "
                             "data=sys.stdin.buffer.read(); print(len(data))")
        result = jobs._pump(process, b"p" * (2 * 1024 * 1024), deadline=time.monotonic() + 3,
                            max_output=256 * 1024)
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(result.interruption)
        self.assertTrue(result.stdout.endswith(b"2097152\n"))
        self.assertEqual(result.stderr, b"e" * 65536)

    def test_output_limit_is_shared_across_both_streams(self):
        process = self.spawn("import sys; sys.stdout.buffer.write(b'a'*800); sys.stdout.flush(); "
                             "sys.stderr.buffer.write(b'b'*800); sys.stderr.flush()")
        result = jobs._pump(process, b"", deadline=time.monotonic() + 3, max_output=1000)
        self.assertEqual(result.interruption, "output_limit_exceeded")
        self.assertEqual(len(result.stdout) + len(result.stderr), 1000)

    def test_exact_output_limit_is_permitted(self):
        process = self.spawn("import sys; sys.stdout.buffer.write(b'a'*1000)")
        result = jobs._pump(process, b"", deadline=time.monotonic() + 3, max_output=1000)
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(result.interruption)
        self.assertEqual(len(result.stdout), 1000)

    def test_timeout_and_cancel_kill_client_with_bounded_partial_output(self):
        for cancellation in (False, True):
            event = threading.Event()
            if cancellation:
                event.set()
            process = self.spawn("import time; time.sleep(30)")
            begun = time.monotonic()
            result = jobs._pump(process, b"x" * (2 * 1024 * 1024), deadline=begun + 0.1,
                                max_output=1000, cancel=event)
            self.assertEqual(result.interruption, "cancelled" if cancellation else "timed_out")
            self.assertIsNotNone(process.poll())
            self.assertLess(time.monotonic() - begun, 1)


if __name__ == "__main__":
    unittest.main()
