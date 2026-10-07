from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from model_harness.errors import ContractError
from model_harness.isolated_execution import ExecutionBundle, ExecutionLimits, OCIExecutor

IMAGE = 'python@sha256:' + 'a' * 64
IMAGE_ID = 'sha256:' + 'b' * 64


def bundle(**kwargs):
    values = {'files': {'algorithm.py': 'print("an arbitrary new task")\n'}, 'stages': {'unseen_problem': ['python', '/workspace/source/algorithm.py']}, 'image': IMAGE}
    values.update(kwargs)
    return ExecutionBundle.create(**values)


class FakeProcess:
    """Only simulates OCI transport; does not run submitted code on the host."""
    def __init__(self, command, *, log=b'container log\n', running=False, exit_code=0, output_writer=None):
        self.command = command
        self.returncode = None if running else exit_code
        read_fd, self.write_fd = os.pipe()
        self.stdout = os.fdopen(read_fd, 'rb')
        self.killed = self.terminated = False
        self._running = running
        if output_writer:
            mount = next(command[index + 1] for index, value in enumerate(command[:-1]) if value == '--mount' and command[index + 1].endswith('dst=/workspace/output'))
            output = Path(mount.split('src=', 1)[1].split(',dst=', 1)[0])
            output_writer(output)
        def write():
            try:
                offset = 0
                while offset < len(log):
                    offset += os.write(self.write_fd, log[offset:])
            except (BrokenPipeError, OSError):
                pass
            finally:
                if not running:
                    self.close_writer()
        self.writer = threading.Thread(target=write, daemon=True)
        self.writer.start()

    def close_writer(self):
        try:
            os.close(self.write_fd)
        except OSError:
            pass

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired(self.command, timeout)
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        self.close_writer()

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.close_writer()


class IsolatedExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'private isolation root'
        self.executor = OCIExecutor('docker')
        self.processes = []
        self.queries = []

    def fake_query(self, argv, timeout=5, *, state=None, cleanup=True):
        self.queries.append(argv)
        if argv[1:3] == ['image', 'inspect']:
            value = {'id': IMAGE_ID, 'repo_digests': ['docker.io/library/' + IMAGE], 'architecture': 'arm64', 'os': 'linux'}
        elif argv[1] == 'inspect':
            value = state if state is not None else {'Status': 'exited', 'Running': False, 'ExitCode': 0, 'OOMKilled': False, 'StartedAt': '2026-10-04T12:00:00Z', 'FinishedAt': '2026-10-04T12:00:01Z'}
        else:
            return subprocess.CompletedProcess(argv, 0 if cleanup or argv[1] != 'rm' else 1, b'', b'')
        return subprocess.CompletedProcess(argv, 0, json.dumps(value).encode(), b'')

    def run_fake(self, selected=None, *, inputs=None, process_options=None, query=None, cancel=None):
        selected = selected or bundle()
        def create(command, **kwargs):
            self.assertEqual(command[0], '/fake/docker')
            self.assertNotIn('shell', kwargs)
            self.assertTrue(kwargs['close_fds'])
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            process = FakeProcess(command, **(process_options or {}))
            self.processes.append(process)
            return process
        with patch.object(self.executor, 'probe', return_value={'available': True, 'runtime': 'docker', 'executable': '/fake/docker', 'version': 'unit-fake', 'reason': None}), patch.object(self.executor, '_query', side_effect=query or self.fake_query), patch('model_harness.isolated_execution.subprocess.Popen', side_effect=create):
            return self.executor.run_stage(selected, 'unseen_problem', expected_bundle_digest=selected.digest, isolated_root=self.root, input_files=inputs, cancel_event=cancel)

    def test_bundle_is_immutable_digest_bound_and_task_agnostic(self):
        files = {'new_science.py': 'print("no predefined model family")'}
        argv = ['python', '/workspace/source/new_science.py', '--novel-parameter', '3']
        selected = bundle(files=files, stages={'unseen_problem': argv})
        digest = selected.digest
        files['new_science.py'] = 'raise SystemExit(3)'
        argv.append('--changed')
        self.assertEqual(selected.digest, digest)
        self.assertEqual(ExecutionBundle.from_dict(selected.to_dict()), selected)
        with self.assertRaises(AttributeError):
            selected.image = 'changed'
        self.assertNotEqual(bundle(files={'algorithm.py': 'changed'}).digest, bundle().digest)

    def test_combined_input_budget_failure_has_actionable_private_path_free_evidence(self):
        first = Path(self.temporary.name) / 'base'; second = Path(self.temporary.name) / 'selected'
        first.write_bytes(b'123456'); second.write_bytes(b'12345')
        result = self.run_fake(bundle(limits={'max_input_bytes': 10}), inputs={'assets/base': first, 'model/selected': second})
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['executed'])
        self.assertEqual(self.processes, [])
        self.assertEqual(result['errors'], ['input_bytes_exceed_approved_limit'])
        self.assertEqual(result['setup_failure'], {'code': 'input_bytes_exceed_approved_limit', 'required_bytes': 11, 'limit_bytes': 10, 'approval_change_required': True, 'model_code_executed': False})
        self.assertNotIn(self.temporary.name, json.dumps(result['setup_failure']))

    def test_invalid_paths_images_limits_and_shell_strings_are_rejected(self):
        for name in ['../escape.py', '/root.py', 'a/../b.py', 'C:\\code.py', 'a,b\n.py', './a.py', 'a//b.py']:
            with self.subTest(name=name), self.assertRaises(ContractError):
                bundle(files={name: 'print(1)'})
        for values in [dict(image='python:latest'), dict(stages={'unseen_problem': 'python code.py'}), dict(stages={'../stage': ['python']}), dict(files={'a.py': '\0'}), dict(files={'a.py': '\ud800'}), dict(limits={'cpus': float('nan')}), dict(limits={'memory_bytes': True}), dict(limits={'tmpfs_bytes': 1024**3}), dict(files={'A.py': 'one', 'a.py': 'two'}), dict(files={'a': 'file', 'a/b.py': 'other'})]:
            with self.subTest(values=values), self.assertRaises(ContractError):
                bundle(**values)

    def test_probe_and_default_construction_never_execute_submitted_code(self):
        with patch('model_harness.isolated_execution.shutil.which', return_value=None), patch('model_harness.isolated_execution.subprocess.Popen') as execute, patch.object(self.executor, '_query') as query:
            selected = bundle()
            self.assertFalse(self.executor.probe()['available'])
            result = self.executor.run_stage(selected, 'unseen_problem', expected_bundle_digest=selected.digest, isolated_root=self.root)
        self.assertEqual(result['status'], 'blocked_environment')
        self.assertFalse(result['executed'])
        self.assertFalse(self.root.exists())
        execute.assert_not_called()
        query.assert_not_called()

    def test_probe_only_queries_installed_daemon(self):
        with patch('model_harness.isolated_execution.shutil.which', return_value='/fake/docker'), patch.object(self.executor, '_query', return_value=subprocess.CompletedProcess([], 0, b'27.1\n', b'')) as query:
            result = self.executor.probe()
        self.assertTrue(result['available'])
        self.assertEqual(query.call_args.args[0], ['/fake/docker', 'version', '--format', '{{.Server.Version}}'])

    def test_digest_stage_and_mount_injection_fail_before_runtime_or_writes(self):
        selected = bundle()
        for digest, stage, root in [('bad', 'unseen_problem', self.root), (selected.digest, 'not-declared', self.root), (selected.digest, 'unseen_problem', Path('relative')), (selected.digest, 'unseen_problem', self.root / 'x,readonly=false')]:
            with self.subTest(stage=stage, root=root), patch.object(self.executor, 'probe') as probe, self.assertRaises(ContractError):
                self.executor.run_stage(selected, stage, expected_bundle_digest=digest, isolated_root=root)
            probe.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_pinned_image_must_be_present_without_automatic_pull(self):
        selected = bundle()
        with patch.object(self.executor, 'probe', return_value={'available': True, 'runtime': 'docker', 'executable': '/fake/docker'}), patch.object(self.executor, '_query', return_value=subprocess.CompletedProcess([], 1, b'', b'missing')), patch('model_harness.isolated_execution.subprocess.Popen') as execute:
            result = self.executor.run_stage(selected, 'unseen_problem', expected_bundle_digest=selected.digest, isolated_root=self.root)
        self.assertEqual(result['status'], 'blocked_environment')
        self.assertEqual(result['errors'], ['pinned_image_not_present_or_not_verified'])
        execute.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_oci_command_enforces_isolation_and_only_stage_inputs(self):
        train = Path(self.temporary.name) / 'train.csv'; train.write_bytes(b'private-training-data')
        holdout = Path(self.temporary.name) / 'holdout.csv'; holdout.write_bytes(b'unseen-final-test-data')
        result = self.run_fake(inputs={'train.csv': train}, process_options={'output_writer': lambda output: (output / 'result.json').write_text('{"measured": 3}')})
        command = self.processes[-1].command
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['executed'])
        self.assertEqual(result['image_id'], IMAGE_ID)
        self.assertEqual(result['exit_code'], 0)
        self.assertFalse(result['public_export_authorized'])
        self.assertFalse(result['creates_training_run'])
        for flag in ['--pull=never', '--read-only', '--cap-drop', '--security-opt', '--pids-limit', '--memory', '--memory-swap', '--cpus', '--ulimit', '--tmpfs']:
            self.assertIn(flag, command)
        self.assertEqual(command[command.index('--network') + 1], 'none')
        self.assertEqual(command[command.index('--user') + 1], '65532:65532')
        self.assertEqual(command[command.index('--security-opt') + 1], 'no-new-privileges')
        mounts = [command[index + 1] for index, value in enumerate(command[:-1]) if value == '--mount']
        self.assertEqual(len(mounts), 3)
        self.assertTrue(all(mount.endswith('readonly') for mount in mounts[:2]))
        self.assertNotIn(str(train), ' '.join(command))
        self.assertNotIn(str(holdout), ' '.join(command))
        job = self.root / result['job_directory']
        self.assertEqual((job / 'input/train.csv').read_bytes(), train.read_bytes())
        self.assertFalse((job / 'input/holdout.csv').exists())
        self.assertEqual(result['inputs'][0]['sha256'], hashlib.sha256(train.read_bytes()).hexdigest())
        self.assertEqual(result['artifacts'][0]['path'], 'result.json')
        self.assertEqual(result['artifacts'][0]['sha256'], hashlib.sha256(b'{"measured": 3}').hexdigest())
        self.assertTrue(result['container_removed'])
        self.assertTrue(any(argv[1:3] == ['rm', '--force'] for argv in self.queries))
        self.assertEqual(json.loads((job / 'execution.json').read_text()), result)

    def test_success_needs_real_state_observation_not_only_cli_zero(self):
        result = self.run_fake(query=lambda argv, timeout=5: self.fake_query(argv, timeout, state={'ExitCode': 0}))
        self.assertNotEqual(result['status'], 'completed')
        self.assertFalse(result['executed'])
        self.assertTrue(result['container_removed'])

    def test_timeout_and_cancellation_stop_and_remove_container(self):
        timed_out = self.run_fake(bundle(limits={'timeout_seconds': .1}), process_options={'running': True, 'log': b''})
        self.assertEqual(timed_out['status'], 'timed_out')
        self.assertTrue(self.processes[-1].terminated)
        self.assertTrue(any(argv[1] == 'stop' for argv in self.queries))
        self.assertTrue(timed_out['container_removed'])
        cancel = threading.Event()
        timer = threading.Timer(.05, cancel.set); timer.start(); self.addCleanup(timer.cancel)
        cancelled = self.run_fake(process_options={'running': True, 'log': b''}, cancel=cancel)
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertTrue(cancelled['container_removed'])

    def test_precancelled_stage_does_not_even_probe(self):
        cancel = threading.Event(); cancel.set(); selected = bundle()
        with patch.object(self.executor, 'probe') as probe:
            result = self.executor.run_stage(selected, 'unseen_problem', expected_bundle_digest=selected.digest, isolated_root=self.root, cancel_event=cancel)
        self.assertEqual(result['status'], 'cancelled')
        self.assertFalse(result['executed'])
        probe.assert_not_called()

    def test_logs_are_streamed_and_bounded_without_losing_exit_truth(self):
        result = self.run_fake(bundle(limits={'max_log_bytes': 1024}), process_options={'log': b'x' * 100_000})
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['log']['truncated'])
        self.assertEqual(result['log']['bytes'], 1024)
        self.assertEqual(result['log']['bytes_observed'], 100_000)
        self.assertEqual((self.root / result['job_directory'] / result['log']['path']).stat().st_size, 1024)

    def test_oversized_and_linked_artifacts_are_not_delivered(self):
        writers = [lambda output: (output / 'huge').write_bytes(b'x' * 2048), lambda output: (output / 'escape').symlink_to('/etc/passwd')]
        for writer in writers:
            with self.subTest(writer=writer):
                result = self.run_fake(bundle(limits={'max_artifact_bytes': 1024}), process_options={'output_writer': writer})
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['artifacts'], [])
                self.assertTrue(result['container_removed'])

    def test_input_symlink_and_limits_fail_without_container_execution(self):
        actual = Path(self.temporary.name) / 'actual'; actual.write_bytes(b'abcd')
        symlink = Path(self.temporary.name) / 'linked'; symlink.symlink_to(actual)
        for source, selected in [(symlink, bundle()), (actual, bundle(limits={'max_input_bytes': 2}))]:
            before = len(self.processes)
            with self.subTest(source=source):
                result = self.run_fake(selected, inputs={'data': source})
                self.assertEqual(result['status'], 'failed')
                self.assertFalse(result['executed'])
                self.assertEqual(len(self.processes), before)

    def test_cleanup_failure_cannot_claim_completed_or_export_artifacts(self):
        result = self.run_fake(query=lambda argv, timeout=5: self.fake_query(argv, timeout, cleanup=False))
        self.assertEqual(result['status'], 'observation_degraded')
        self.assertFalse(result['container_removed'])
        self.assertIn('container_cleanup_unconfirmed', result['errors'])
        self.assertEqual(result['artifacts'], [])

    def test_nonzero_and_oom_results_are_failures(self):
        state = {'Status': 'exited', 'Running': False, 'ExitCode': 137, 'OOMKilled': True, 'StartedAt': '2026-10-04T12:00:00Z', 'FinishedAt': '2026-10-04T12:00:01Z'}
        result = self.run_fake(process_options={'exit_code': 137}, query=lambda argv, timeout=5: self.fake_query(argv, timeout, state=state))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['exit_code'], 137)
        self.assertTrue(result['container_state']['OOMKilled'])
        self.assertTrue(result['container_removed'])

    def test_stage_limits_preserve_legacy_digest_and_cannot_expand_default_budget(self):
        legacy = bundle(limits={'timeout_seconds': 180})
        old_payload = legacy.to_dict()
        self.assertNotIn('stage_limits', old_payload)
        expected = hashlib.sha256(json.dumps(old_payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        self.assertEqual(ExecutionBundle.from_dict(old_payload).digest, expected)
        limited = bundle(limits={'timeout_seconds': 180}, stage_limits={'unseen_problem': {'timeout_seconds': 60}})
        self.assertEqual(limited.limits.timeout_seconds, 180)
        self.assertEqual(limited.limits_for_stage('unseen_problem').timeout_seconds, 60)
        self.assertEqual(ExecutionBundle.from_dict(limited.to_dict()).digest, limited.digest)
        self.assertNotEqual(limited.digest, legacy.digest)
        for limits in ({'unseen_problem': {'timeout_seconds': 181}}, {'not-declared': {'timeout_seconds': 1}},
                       {'unseen_problem': {'cpus': 2}}, {'unseen_problem': {'unknown': 1}}, {'unseen_problem': {'timeout_seconds': True}}):
            with self.subTest(stage_limits=limits), self.assertRaises(ContractError):
                bundle(limits={'timeout_seconds': 180}, stage_limits=limits)

    def test_stage_timeout_and_command_use_the_tighter_budget_and_report_it(self):
        limited = bundle(limits={'timeout_seconds': 180, 'cpus': 2},
                         stage_limits={'unseen_problem': {'timeout_seconds': .1, 'cpus': .5, 'memory_bytes': 128 * 1024**2}})
        result = self.run_fake(limited, process_options={'running': True, 'log': b''})
        self.assertEqual(result['status'], 'timed_out')
        self.assertEqual(result['limits']['timeout_seconds'], .1)
        self.assertEqual(result['limits']['memory_bytes'], 128 * 1024**2)
        command = self.processes[-1].command
        self.assertEqual(command[command.index('--memory') + 1], str(128 * 1024**2))
        self.assertEqual(command[command.index('--cpus') + 1], '0.5')
        self.assertTrue(result['container_removed'])


if __name__ == '__main__':
    unittest.main()
