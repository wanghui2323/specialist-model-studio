from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from model_harness.cli import main
from model_harness.startup_lifecycle import WRITER_LEASE_FILENAME, run_owned_launcher, wait_for_writer_release, writer_wait_seconds

ROOT = Path(__file__).resolve().parents[1]

_WRITER = r'''
import fcntl,json,signal,socket,sys,time
from pathlib import Path
path=Path(sys.argv[1]);path.parent.mkdir(parents=True,exist_ok=True)
with path.open('a+b') as lock:
    lock.write(b'fixture writer lease - do not rewrite');lock.flush()
    fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
    def shutdown(_signum,_frame):
        listener.close()
        print('listener-closed',flush=True)
        time.sleep(float(sys.argv[2]))
        raise SystemExit(0)
    signal.signal(signal.SIGTERM,shutdown)
    print(json.dumps({'port':listener.getsockname()[1]}),flush=True)
    while True:time.sleep(.05)
'''


@unittest.skipIf(os.name != 'posix', 'the local bash launcher uses a POSIX writer lease')
class StartupLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.processes = []
        self.addCleanup(self.stop_fixtures)

    def stop_fixtures(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=3)
            for stream in (process.stdout, process.stderr):
                if stream:
                    stream.close()

    def writer(self, delay=.35):
        runs = self.root / ('runs-' + str(len(self.processes)))
        process = subprocess.Popen([sys.executable, '-u', '-c', _WRITER, str(runs / WRITER_LEASE_FILENAME), str(delay)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.processes.append(process)
        observed = json.loads(process.stdout.readline())
        return process, runs, observed['port']

    def test_actual_listener_close_does_not_end_the_writer_lease(self):
        from model_harness.server import _RunsWorkspaceLease
        self.assertEqual(WRITER_LEASE_FILENAME, _RunsWorkspaceLease.FILENAME)
        process, runs, port = self.writer()
        path = runs / WRITER_LEASE_FILENAME
        contents, inode = path.read_bytes(), path.stat().st_ino
        process.terminate()
        self.assertEqual(process.stdout.readline().strip(), 'listener-closed')
        with self.assertRaises(OSError):
            socket.create_connection(('127.0.0.1', port), timeout=.1)
        notes = []
        waited = wait_for_writer_release(runs, timeout_seconds=2, on_wait=lambda: notes.append('waiting'))
        self.assertGreaterEqual(waited, .2)
        self.assertEqual(notes, ['waiting'])
        process.wait(timeout=2)
        self.assertEqual(path.read_bytes(), contents)
        self.assertEqual(path.stat().st_ino, inode)
        lease = _RunsWorkspaceLease(runs)
        lease.acquire(); lease.release()

    def test_timeout_does_not_kill_the_writer_remove_or_rewrite_its_lock(self):
        process, runs, _port = self.writer()
        path = runs / WRITER_LEASE_FILENAME
        contents, inode = path.read_bytes(), path.stat().st_ino
        with self.assertRaisesRegex(RuntimeError, 'still holds'):
            wait_for_writer_release(runs, timeout_seconds=.1)
        self.assertIsNone(process.poll())
        self.assertEqual(path.read_bytes(), contents)
        self.assertEqual(path.stat().st_ino, inode)
        import fcntl
        with path.open('rb') as handle, self.assertRaises(BlockingIOError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_cli_serve_waits_before_constructing_backend(self):
        process, runs, _port = self.writer()
        process.terminate(); process.stdout.readline()
        def ready_to_serve(**kwargs):
            from model_harness.server import _RunsWorkspaceLease
            lease = _RunsWorkspaceLease(kwargs['runs_dir'])
            lease.acquire(); lease.release()
        with patch('model_harness.server.serve', side_effect=ready_to_serve) as serve, patch.dict(os.environ, {'MODEL_HARNESS_WRITER_WAIT_SECONDS': '2'}), contextlib.redirect_stderr(io.StringIO()):
            result = main(['serve', '--runs-dir', str(runs), '--port', '0'])
        self.assertEqual(result, 0)
        serve.assert_called_once()
        process.wait(timeout=2)

    def test_cli_timeout_never_constructs_a_second_backend(self):
        process, runs, _port = self.writer()
        with patch('model_harness.server.serve') as serve, patch.dict(os.environ, {'MODEL_HARNESS_WRITER_WAIT_SECONDS': '0'}), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = main(['serve', '--runs-dir', str(runs)])
        self.assertNotEqual(result, 0)
        serve.assert_not_called()
        self.assertIsNone(process.poll())

    def test_fresh_workspace_does_not_create_a_fake_lock(self):
        runs = self.root / 'fresh'
        self.assertEqual(wait_for_writer_release(runs, timeout_seconds=0), 0)
        self.assertFalse(runs.exists())
        with self.assertRaises(RuntimeError):
            writer_wait_seconds({'MODEL_HARNESS_WRITER_WAIT_SECONDS': 'nan'})
        with self.assertRaises(RuntimeError):
            writer_wait_seconds({'MODEL_HARNESS_WRITER_WAIT_SECONDS': '-1'})
        self.assertEqual(writer_wait_seconds({'MODEL_HARNESS_WRITER_WAIT_SECONDS': '.25'}), .25)

    def test_signal_forwarding_waits_for_owned_launcher_graceful_exit(self):
        ready = self.root / 'ready'
        stopped = self.root / 'stopped'
        shell = self.root / 'launcher.sh'
        shell.write_text('''#!/usr/bin/env bash
trap 'sleep .25; printf done > "$STOPPED"; exit 0' TERM
printf ready > "$READY"
while true; do sleep .02; done
''')
        parent_code = 'from model_harness.startup_lifecycle import run_owned_launcher; import os,sys; from pathlib import Path; sys.exit(run_owned_launcher(["bash",sys.argv[1]],cwd=Path(sys.argv[2]),env=os.environ))'
        environment = dict(os.environ, PYTHONPATH=str(ROOT), READY=str(ready), STOPPED=str(stopped))
        parent = subprocess.Popen([sys.executable, '-c', parent_code, str(shell), str(self.root)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.processes.append(parent)
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(ready.exists())
        started = time.monotonic(); parent.terminate()
        status = parent.wait(timeout=3)
        self.assertEqual(status, 143)
        self.assertGreaterEqual(time.monotonic() - started, .2)
        self.assertEqual(stopped.read_text(), 'done')

    def test_launcher_cleanup_waits_for_owned_backend_and_leaves_reused_pid_alone(self):
        source = (ROOT / 'scripts/start_conversation_harness.sh').read_text()
        cleanup = source[source.index('cleanup() {'):source.index('\nif curl --fail --silent --max-time 2', source.index('cleanup() {'))]
        owned = self.root / 'owned.py'
        released = self.root / 'released'
        ready = self.root / 'backend-ready'
        owned.write_text('''import signal,sys,time
from pathlib import Path
ready,done=map(Path,sys.argv[1:])
def stop(*args):
 time.sleep(.25);done.write_text('released');raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
ready.write_text('ready')
while True:time.sleep(.02)
''')
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(10)'])
        self.processes.append(unrelated)
        script = self.root / 'owned-launcher.sh'
        script.write_text('set -euo pipefail\n"$PYTHON" "$OWNED" "$READY" "$RELEASED" &\nBACKEND_PID="$!"\nSTARTED_BACKEND=1\nSTARTED_AGENT=0\nAGENT_PID="$REUSED_PID"\n' + cleanup + '\nwait "$BACKEND_PID"\n')
        environment = dict(os.environ, PYTHON=sys.executable, OWNED=str(owned), READY=str(ready), RELEASED=str(released), REUSED_PID=str(unrelated.pid))
        launcher = subprocess.Popen(['bash', str(script)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.processes.append(launcher)
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(ready.exists())
        launcher.terminate()
        self.assertEqual(launcher.wait(timeout=3), 143)
        self.assertEqual(released.read_text(), 'released')
        self.assertIsNone(unrelated.poll())

    def test_supervision_uses_a_separate_session_and_restores_signal_handlers(self):
        process = Mock(); process.wait.return_value = 7
        before = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
        with patch('model_harness.startup_lifecycle.subprocess.Popen', return_value=process) as launch:
            self.assertEqual(run_owned_launcher(['bash', 'fixture.sh'], cwd=self.root, env={}), 7)
        self.assertTrue(launch.call_args.kwargs['start_new_session'])
        self.assertEqual({number: signal.getsignal(number) for number in before}, before)


if __name__ == '__main__':
    unittest.main()
