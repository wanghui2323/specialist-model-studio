from __future__ import annotations

import contextlib
import http.client
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch
from urllib.request import urlopen

from model_harness.errors import HarnessError
from model_harness.io_utils import read_json, write_json
from model_harness.server import _RunsWorkspaceLease, serve
from model_harness.service import RunService
from model_harness.state import RunState

ROOT = Path(__file__).resolve().parents[1]

_SSE_SERVER = r'''
import sys,time
from pathlib import Path
import model_harness.server as server
from model_harness.io_utils import write_json
from model_harness.state import RunState
from tests.test_conversation_stream import conversation_view
root=Path(sys.argv[1]);port=int(sys.argv[2]);real_create=server.create_app

def fixture_app(*args,**kwargs):
    app=real_create(*args,**kwargs)
    runtime=app.state.conversation_runtime
    runtime.start=lambda:None
    runtime.stop=lambda:None
    runtime.runtime_status=lambda:{'available':True,'conversation_projector_revision':'3.0'}
    task=app.state.training_workspace.create_task('shutdown SSE fixture','A local transport fixture without model provider access')
    task_id=task['task_id']
    runtime.conversation=lambda owner:conversation_view(task_id=owner,projector_revision='3.0')
    worker_dir=root/'runs'/'owned-shutdown-fixture'
    worker=RunState(worker_dir,task_id,'owned-shutdown-fixture','fixture-only')
    worker.transition('queued');worker.transition('preflight');worker.transition('training')
    def owned_work():
        while not RunState.load(worker_dir).cancel_requested:time.sleep(.02)
        time.sleep(.2)
        RunState.load(worker_dir).cancel('shutdown acknowledged')
        (root/'worker-stopped').write_text('actual worker function returned')
        return worker_dir
    service=app.state.run_service
    service._futures[worker_dir.name]=service._executor.submit(owned_work)
    write_json(root/'fixture-task.json',{'task_id':task_id})
    return app
server.create_app=fixture_app
server.serve(root/'runs',host='127.0.0.1',port=port)
'''


class ServerShutdownTests(unittest.TestCase):
    def test_serve_sets_a_bounded_http_drain_without_changing_the_app_lease(self):
        marker = object()
        with patch('model_harness.server.create_app', return_value=marker), patch('uvicorn.run') as run, patch.dict(os.environ, {'MODEL_HARNESS_GRACEFUL_SHUTDOWN_SECONDS': '.25'}):
            serve('fixture-runs', port=12345)
        run.assert_called_once_with(marker, host='127.0.0.1', port=12345, timeout_graceful_shutdown=.25)
        for value in ['nan', 'inf', '-1', '61', 'invalid']:
            with self.subTest(value=value), patch.dict(os.environ, {'MODEL_HARNESS_GRACEFUL_SHUTDOWN_SECONDS': value}), patch('uvicorn.run') as run, self.assertRaises(RuntimeError):
                serve('fixture-runs')
            run.assert_not_called()

    @unittest.skipIf(os.name != 'posix', 'SIGTERM/flock process fixture is POSIX')
    def test_open_real_product_sse_cannot_hold_shutdown_lease_forever(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0)); port = reservation.getsockname()[1]
            log_path = root / 'server.log'
            environment = dict(os.environ, PYTHONPATH=str(ROOT), MODEL_HARNESS_GRACEFUL_SHUTDOWN_SECONDS='.2')
            with log_path.open('wb') as log:
                process = subprocess.Popen([sys.executable, '-u', '-c', _SSE_SERVER, str(root), str(port)], cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            connection = None
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail('fixture server failed: ' + log_path.read_text())
                    try:
                        with urlopen(f'http://127.0.0.1:{port}/health', timeout=.3) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.04)
                else:
                    self.fail('fixture server did not listen: ' + log_path.read_text())
                task_id = read_json(root / 'fixture-task.json')['task_id']
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                connection.request('GET', f'/tasks/{task_id}/conversation/stream')
                response = connection.getresponse()
                self.assertEqual(response.status, 200, log_path.read_text())
                self.assertIn('text/event-stream', response.getheader('Content-Type'))
                self.assertTrue(response.readline(), 'the real product stream must send a frame')
                lock_path = root / 'runs' / _RunsWorkspaceLease.FILENAME
                inode = lock_path.stat().st_ino
                started = time.monotonic()
                process.send_signal(signal.SIGTERM)
                # Deliberately leave the HTTP response and TCP connection open.
                process.wait(timeout=6)
                self.assertLess(time.monotonic() - started, 6)
                self.assertTrue((root / 'worker-stopped').exists(), log_path.read_text())
                state = read_json(root / 'runs/owned-shutdown-fixture/run_state.json')
                self.assertEqual(state['status'], 'cancelled')
                self.assertEqual(state['cancel_request']['kind'], 'service_shutdown')
                self.assertEqual(lock_path.stat().st_ino, inode)
                lease = _RunsWorkspaceLease(root / 'runs')
                lease.acquire(); lease.release()
            finally:
                if connection:
                    connection.close()
                if process.poll() is None:
                    # Only this test's random-port child is ever forced down on
                    # failure; no production PID or global process lookup.
                    process.kill(); process.wait(timeout=3)

    def test_close_requests_only_owned_training_and_waits_for_actual_worker_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = RunService(root, registry=object(), max_workers=1, recover=False)
            self.addCleanup(service.close)
            release = Event(); started = Event(); exited = Event()
            owned = RunState(root / 'owned', 'fixture-task', 'owned', 'fixture')
            owned.transition('queued'); owned.transition('preflight'); owned.transition('training')
            foreign = RunState(root / 'not-owned', 'foreign-task', 'not-owned', 'fixture')
            foreign.transition('queued'); foreign.transition('preflight'); foreign.transition('training')
            queued = RunState(root / 'queued-owned', 'fixture-task', 'queued-owned', 'fixture')
            queued.transition('queued')
            def worker():
                started.set()
                release.wait(timeout=5)
                RunState.load(root / 'owned').cancel('worker reached safe boundary')
                exited.set()
                return root / 'owned'
            service._futures['owned'] = service._executor.submit(worker)
            self.assertTrue(started.wait(1))
            service._futures['queued-owned'] = service._executor.submit(lambda: self.fail('queued cancelled worker must never execute'))
            stopped = Event()
            closer = Thread(target=lambda: (service.close(), stopped.set()))
            closer.start()
            try:
                deadline = time.monotonic() + 2
                while not RunState.load(root / 'owned').cancel_requested and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(RunState.load(root / 'owned').cancel_requested)
                self.assertEqual(RunState.load(root / 'owned').status, 'training')
                self.assertFalse(stopped.is_set())
                self.assertFalse(RunState.load(root / 'not-owned').cancel_requested)
                deadline = time.monotonic() + 2
                while RunState.load(root / 'queued-owned').status != 'cancelled' and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(RunState.load(root / 'queued-owned').status, 'cancelled')
                with patch('model_harness.service.prepare_run') as prepare, self.assertRaises(HarnessError):
                    service.submit({}, run_id='after-shutdown')
                prepare.assert_not_called()
            finally:
                release.set(); closer.join(timeout=3)
            self.assertTrue(exited.is_set())
            self.assertTrue(stopped.is_set())

    def test_legacy_sample_worker_is_also_drained_without_claiming_it_was_force_stopped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = RunService(root, registry=object(), recover=False)
            self.addCleanup(service.close)
            state = RunState(root / 'legacy-sample', 'fixture-task', 'legacy-sample', 'fixture')
            state.transition('queued')
            write_json(root / 'legacy-sample/task_contract.json', {'recipe': 'tabular-regression'})
            running = Event(); release = Event(); stopped = Event()
            def predict(_sample, **kwargs):
                running.set(); release.wait(timeout=4)
                return {'status': 'passed'}
            with patch('model_harness.service.SampleInference') as sample:
                sample.return_value.run.side_effect = predict
                caller = Thread(target=lambda: service.sample_inference('legacy-sample', {}))
                caller.start(); self.assertTrue(running.wait(1))
                closer = Thread(target=lambda: (service.close(), stopped.set())); closer.start()
                try:
                    deadline = time.monotonic() + 2
                    while not service.sample_inference_background_actions('fixture-task')[0]['cancel_requested'] and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertFalse(stopped.is_set())
                    self.assertTrue(service.sample_inference_background_actions('fixture-task')[0]['worker_running'])
                finally:
                    release.set(); caller.join(timeout=3); closer.join(timeout=3)
            self.assertTrue(stopped.is_set())
            records = list((root / 'legacy-sample/evidence/sample_jobs').glob('*.json'))
            self.assertEqual(read_json(records[0])['status'], 'completed')

    def test_close_waits_for_external_generic_inference_worker_after_cancel_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = RunService(root, registry=object(), recover=False)
            self.addCleanup(service.close)
            state = RunState(root / 'sample', 'fixture-task', 'sample', 'fixture')
            state.transition('queued')
            write_json(root / 'sample/task_contract.json', {'recipe': 'generic-isolated-execution'})
            running = Event(); requested = Event(); release = Event(); finished = Event()
            def prediction(_sample, **kwargs):
                running.set()
                while not kwargs['cancel_check']():time.sleep(.01)
                requested.set(); release.wait(timeout=4)
                raise RuntimeError('fixture worker acknowledges cancellation')
            def invoke():
                with contextlib.suppress(RuntimeError):
                    service.sample_inference('sample', {})
                finished.set()
            stopped = Event()
            with patch('model_harness.service.SampleInference') as sample:
                sample.return_value.run.side_effect = prediction
                caller = Thread(target=invoke); caller.start(); self.assertTrue(running.wait(1))
                closer = Thread(target=lambda: (service.close(), stopped.set())); closer.start()
                try:
                    self.assertTrue(requested.wait(2))
                    self.assertFalse(stopped.is_set())
                    self.assertFalse(finished.is_set())
                    actions = service.sample_inference_background_actions('fixture-task')
                    self.assertEqual(actions[0]['status'], 'cancel_requested')
                    self.assertTrue(actions[0]['worker_running'])
                finally:
                    release.set(); caller.join(timeout=3); closer.join(timeout=3)
            self.assertTrue(finished.is_set())
            self.assertTrue(stopped.is_set())
            self.assertEqual(service.sample_inference_background_actions('fixture-task'), [])


if __name__ == '__main__':
    unittest.main()
