from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from model_harness.execution_workspace import ExecutionWorkspace, digest
from model_harness.io_utils import read_json, sha256_file, write_json
from model_harness.server import create_app
from tests.contract_confirmation import contract_confirmation_payload
from tests.test_generic_protocol import execution_spec
from tests.run_authorization import AGENT_BRIDGE_HEADERS, TEST_AGENT_BRIDGE_TOKEN, request_task_run_authorization


class FixtureOCIExecutor:
    """Signed transport fixtures only: never import or run submitted source."""
    def __init__(self):
        self.calls = []
        self.lock = Lock()
        self.fail_qualification = False
        self.result_overrides = {}
        self.release_qualification = Event()
        self.release_qualification.set()

    def probe(self):
        return {'available': True, 'runtime': 'fixture', 'executable': '/fixture/never-executed', 'version': 'test-only', 'reason': None}

    def _query(self, argv):
        return subprocess.CompletedProcess(argv, 0, b'{}', b'')

    def run_stage(self, bundle, stage, *, expected_bundle_digest, isolated_root, input_files, cancel_event=None):
        if bundle.digest != expected_bundle_digest:
            raise AssertionError('fixture received wrong bundle digest')
        with self.lock:
            self.calls.append({'stage': stage, 'input_keys': tuple(input_files), 'bundle_digest': bundle.digest})
        if stage == 'qualify':
            deadline = time.monotonic() + 5
            while not self.release_qualification.wait(.01):
                if cancel_event and cancel_event.is_set():
                    break
                if time.monotonic() > deadline:
                    raise AssertionError('test qualification release was not signalled')
        execution_id = 'stage-' + uuid4().hex
        job = Path(isolated_root) / execution_id
        output = job / 'output'; output.mkdir(parents=True)
        logs = job / 'logs'; logs.mkdir()
        log = 'intentional fixture entrypoint failure\n' if self.fail_qualification and stage == 'qualify' else 'fixture transport evidence; no source executed\n'
        (logs / 'stdio.log').write_text(log)
        if stage == 'qualify':
            write_json(output / 'qualification.json', {'valid': True, 'checks': [{'name': name, 'passed': True} for name in ['input_validation', 'invalid_input_rejected', 'parameter_update', 'model_reload', 'prediction_shape']]})
        elif stage == 'train':
            (output / 'model').mkdir()
            (output / 'model/custom.weights').write_bytes(b'opaque fixture weights, never host-loaded')
            write_json(output / 'train_result.json', {'selected_model': 'unseen_candidate', 'validation_candidates': {'unseen_candidate': {'constraint_violation': .1}}, 'split_counts': {'train': 3, 'validation': 1, 'test': 999999}, 'model_files': ['model/custom.weights']})
        elif stage == 'evaluate':
            write_json(output / 'evaluate_result.json', {'metrics': {'constraint_violation': .12}, 'sample_count': 2, 'failure_samples': []})
        elif stage == 'predict':
            write_json(output / 'infer_result.json', {'prediction': {'new_coordinate': 3.2}})
        else:
            raise AssertionError('unexpected generic stage')
        if stage in self.result_overrides:
            filenames = {'qualify': 'qualification.json', 'train': 'train_result.json', 'evaluate': 'evaluate_result.json', 'predict': 'infer_result.json'}
            write_json(output / filenames[stage], self.result_overrides[stage])
        failed = self.fail_qualification and stage == 'qualify'
        evidence = {'schema_version': '0.1', 'object_type': 'IsolatedStageExecution', 'execution_id': execution_id, 'job_directory': execution_id,
            'stage': stage, 'bundle_sha256': bundle.digest, 'image_reference': bundle.image, 'image': {'id': 'sha256:' + 'b' * 64},
            'runtime': {'runtime': 'fixture', 'version': 'test-only'}, 'status': 'failed' if failed else 'completed', 'executed': True,
            'exit_code': 2 if failed else 0, 'container_removed': True, 'duration_seconds': .001,
            'errors': ['fixture_entrypoint_failed'] if failed else [], 'private_evidence': True, 'public_export_authorized': False,
            'inputs': [{'path': name, 'bytes': path.stat().st_size, 'sha256': sha256_file(path)} for name, path in input_files.items()],
            'artifacts': [{'path': path.relative_to(output).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha256_file(path)} for path in sorted(output.rglob('*')) if path.is_file()],
            'log': {'path': 'logs/stdio.log', 'bytes': (logs / 'stdio.log').stat().st_size, 'sha256': sha256_file(logs / 'stdio.log'), 'truncated': False, 'private': True}}
        evidence['evidence_sha256'] = digest(evidence)
        write_json(job / 'execution.json', evidence)
        return evidence


class ExecutionWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = patch.dict('os.environ', {'MODEL_HARNESS_AGENT_BRIDGE_TOKEN': TEST_AGENT_BRIDGE_TOKEN, 'MODEL_HARNESS_EXECUTION_IMAGE': 'python@sha256:' + 'a' * 64, 'MODEL_HARNESS_ISOLATED_ROOT': str(self.root / 'isolated')})
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.app = create_app(self.root / 'runs')
        self.workspace = self.app.state.training_workspace
        self.store = self.app.state.execution_workspace
        self.fake = FixtureOCIExecutor()
        self.store.executor = self.fake
        self.store.isolated_root = self.root / 'isolated'
        self.plugin_patch = patch.object(self.app.state.run_service.registry.get_recipe('generic-isolated-execution'), 'executor', self.fake)
        self.plugin_patch.start(); self.addCleanup(self.plugin_patch.stop)
        runtime = self.app.state.conversation_runtime
        self.start = patch.object(runtime, 'start'); self.start.start(); self.addCleanup(self.start.stop)
        self.stop = patch.object(runtime, 'stop'); self.stop.start(); self.addCleanup(self.stop.stop)
        self.client = TestClient(self.app)
        self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.fake.release_qualification.set)
        task_response = self.client.post('/tasks', json={'name': '未预设的曲面残差任务', 'business_goal': '根据坐标测量估计未知曲面的约束残差', 'capability_request': {'modality': 'tabular', 'objective': 'novel_geometric_constraint_prediction', 'target_kind': 'coordinate_graph'}})
        self.assertEqual(task_response.status_code, 201, task_response.text)
        self.task = task_response.json()['task']
        self.task_id = self.task['task_id']
        self.base = f'/tasks/{self.task_id}'
        self.assertIsNone(self.task.get('recipe_id'))
        # A structured unfamiliar objective stays authoritative even when
        # wording contains coordinates: do not force an object-detection turn.
        self.assertEqual(self.task['capability_decision']['status'], 'resolved')
        self.assertIsNone(self.task.get('recipe_id'))
        upload = self.client.post(self.base + '/materials', content=b'id,input,target\n0,a,1\n1,b,2\n2,c,3\n3,d,4\n4,e,5\n5,f,6\n', headers={'X-Filename': 'samples.csv', 'X-Request-ID': 'workspace-material'})
        self.assertEqual(upload.status_code, 201, upload.text)
        self.material = upload.json()['material']
        self.spec = execution_spec()
        self.spec['capability'] = dict(self.task['capability_request'])
        self.spec['data_mapping'] = [dict(material_id=self.material['material_id'], inspection_sha256=self.material['inspection_sha256'], split=split, csv_rows=rows) for split, rows in [('train', [0, 1, 2]), ('validation', [3]), ('test', [4, 5])]]

    def create_proposal(self, *, request='proposal-request', spec=None, revision=None):
        return self.client.post(self.base + '/execution-proposals', json={'base_spec_revision': revision if revision is not None else self.task['current_spec_revision'], 'execution_spec': spec or self.spec, 'request_id': request})

    def proposal(self, **kwargs):
        response = self.create_proposal(**kwargs)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['proposal']

    def qualify(self, proposal, *, headers=AGENT_BRIDGE_HEADERS, actor='user', expected=None):
        return self.client.post(f"{self.base}/execution-proposals/{proposal['proposal_id']}/qualify", headers=headers,
            json={'expected_proposal_sha256': expected or proposal['proposal_sha256'], 'approval': {'actor': actor, 'checkpoint_id': 'native-qualify-fixture'}})

    def await_qualification(self, proposal):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            response = self.client.get(f"{self.base}/execution-proposals/{proposal['proposal_id']}")
            self.assertEqual(response.status_code, 200, response.text)
            found = response.json()['proposal']
            if found['status'] != 'qualifying':
                return found
            time.sleep(.01)
        self.fail('qualification fixture did not settle')

    def qualified_proposal(self):
        proposal = self.proposal()
        accepted = self.qualify(proposal)
        self.assertEqual(accepted.status_code, 202, accepted.text)
        found = self.await_qualification(proposal)
        self.assertEqual(found['status'], 'qualified', found)
        return found

    def activate(self, proposal, *, headers=AGENT_BRIDGE_HEADERS, qualification_sha=None):
        qualification = proposal['qualification']
        return self.client.post(f"{self.base}/execution-proposals/{proposal['proposal_id']}/activate", headers=headers,
            json={'expected_proposal_sha256': proposal['proposal_sha256'], 'qualification_id': qualification['qualification_id'],
                'expected_qualification_sha256': qualification_sha or qualification['qualification_sha256'], 'approval': {'actor': 'user', 'checkpoint_id': 'native-activate-fixture'}})

    def activated_proposal(self):
        proposal = self.qualified_proposal()
        response = self.activate(proposal)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_schema_create_idempotency_owner_and_stale_goal(self):
        info = self.client.get(self.base + '/execution-workspace')
        self.assertEqual(info.status_code, 200, info.text)
        self.assertIn('execution_spec_schema', info.json()['execution_workspace'])
        guide = info.json()['execution_workspace']['protocol']
        self.assertEqual(guide['working_directory'], '/workspace/output')
        self.assertIn('empty', guide['working_directory_initial_state'])
        self.assertEqual(guide['source_argv_example'], ['python', '/workspace/source/run.py', 'qualify'])
        self.assertIn('/workspace/source/<file>', guide['instructions'])
        remote_info = self.client.get(self.base + '/execution-workspace', headers={'X-Model-Harness-Projection': 'agent-execution-v1'})
        self.assertEqual(remote_info.json()['execution_workspace']['protocol']['working_directory'], '/workspace/output')
        self.assertEqual(remote_info.json()['execution_workspace']['execution_spec_schema']['x-protocol']['working_directory'], '/workspace/output')
        self.assertEqual(remote_info.json()['execution_workspace']['protocol']['stage_result_contracts'], guide['stage_result_contracts'])
        self.assertIn('existing key', ' '.join(guide['stage_result_contracts']['train']['requirements']))
        proposal = self.proposal()
        replay = self.proposal()
        self.assertEqual(replay['proposal_id'], proposal['proposal_id'])
        self.assertEqual(replay['proposal_sha256'], proposal['proposal_sha256'])
        changed = deepcopy(self.spec); changed['config']['new_value'] = 3
        self.assertEqual(self.create_proposal(spec=changed).status_code, 409)
        self.assertEqual(self.create_proposal(request='stale', revision=self.task['current_spec_revision'] + 1).status_code, 409)
        changed = deepcopy(self.spec); changed['capability']['objective'] = 'unrelated_goal'
        self.assertEqual(self.create_proposal(request='goal-change', spec=changed).status_code, 422)
        foreign = self.client.post('/tasks', json={'name': 'other', 'business_goal': '另一任务'}).json()['task']['task_id']
        self.assertEqual(self.client.get(f"/tasks/{foreign}/execution-proposals/{proposal['proposal_id']}").status_code, 404)
        current = self.client.get(self.base).json()['task']
        self.assertIsNone(current.get('dataset_id'))
        self.assertEqual(current['run_ids'], [])
        self.assertFalse(self.fake.calls)

    def test_invalid_create_and_uncommitted_orphan_can_retry(self):
        bad = deepcopy(self.spec); bad['data_mapping'][-1]['csv_rows'] = [999]
        self.assertEqual(self.create_proposal(spec=bad).status_code, 422)
        proposals = self.workspace._task_dir(self.task_id) / 'execution_proposals'
        self.assertEqual(list(proposals.glob('execution-*')), [])
        missing_asset = deepcopy(self.spec); missing_asset['asset_ids'] = ['asset-' + 'd' * 24]
        self.assertEqual(self.create_proposal(spec=missing_asset).status_code, 404)
        self.assertEqual(list(proposals.glob('execution-*')), [])
        proposal_id = 'execution-' + digest({'task_id': self.task_id, 'request_id': 'proposal-request'})[:24]
        orphan = proposals / proposal_id; orphan.mkdir()
        (orphan / 'unfinished-private-copy').write_text('stale staging only')
        proposal = self.proposal()
        self.assertEqual(proposal['proposal_id'], proposal_id)
        self.assertFalse((orphan / 'unfinished-private-copy').exists())
        (orphan / 'state.json').unlink()
        resumed = self.proposal()
        self.assertEqual(resumed['status'], 'proposed')
        self.assertIsNone(resumed['qualification'])

    def test_native_bridge_proof_and_exact_proposal_are_required(self):
        proposal = self.proposal()
        self.assertEqual(self.qualify(proposal, headers={}).status_code, 403)
        self.assertEqual(self.qualify(proposal, headers={'X-Model-Harness-Agent-Token': 'forged'}).status_code, 403)
        self.assertEqual(self.qualify(proposal, actor='assistant').status_code, 409)
        self.assertEqual(self.qualify(proposal, expected='0' * 64).status_code, 409)
        self.assertFalse(self.fake.calls)
        self.fake.release_qualification.clear()
        accepted = self.qualify(proposal)
        self.assertEqual(accepted.status_code, 202, accepted.text)
        self.assertEqual(accepted.json()['proposal']['status'], 'qualifying')
        duplicate = self.qualify(proposal)
        self.assertEqual(duplicate.json()['proposal']['qualification']['qualification_id'], accepted.json()['proposal']['qualification']['qualification_id'])
        self.fake.release_qualification.set()
        qualified = self.await_qualification(proposal)
        self.assertEqual(qualified['status'], 'qualified', qualified)
        self.assertFalse(qualified['qualification']['creates_training_run'])
        self.assertEqual(self.client.get(self.base).json()['task']['run_ids'], [])
        self.assertEqual(len(self.fake.calls), 1)
        self.assertFalse(any(key.startswith('test/') for key in self.fake.calls[0]['input_keys']))

    def test_failure_logs_preserved_and_new_qualification_can_recover(self):
        self.fake.fail_qualification = True
        proposal = self.proposal()
        self.assertEqual(self.qualify(proposal).status_code, 202)
        failed = self.await_qualification(proposal)
        self.assertEqual(failed['status'], 'qualification_failed')
        evidence = failed['qualification']['execution']
        self.assertEqual(evidence['exit_code'], 2)
        log = self.store.isolated_root / evidence['job_directory'] / evidence['log']['path']
        self.assertEqual(sha256_file(log), evidence['log']['sha256'])
        self.assertIn('intentional fixture entrypoint failure', log.read_text())
        self.assertIn('intentional fixture entrypoint failure', failed['qualification']['log_tail'])
        self.assertTrue(failed['qualification']['log_is_untrusted_execution_output'])
        self.assertIsNone(self.client.get(self.base).json()['task'].get('dataset_id'))
        failed_id = failed['qualification']['qualification_id']
        self.fake.fail_qualification = False
        self.assertEqual(self.qualify(proposal).status_code, 202)
        recovered = self.await_qualification(proposal)
        self.assertEqual(recovered['status'], 'qualified', recovered)
        self.assertNotEqual(recovered['qualification']['qualification_id'], failed_id)
        self.assertTrue((self.store._dir(self.task_id, proposal['proposal_id']) / 'qualifications' / failed_id / 'qualification.json').is_file())

    def test_restart_marks_pending_qualification_interrupted_without_fake_success(self):
        proposal = self.qualified_proposal()
        path = self.store._dir(self.task_id, proposal['proposal_id'])
        write_json(path / 'state.json', {'status': 'qualifying', 'qualification_id': 'qualification-' + 'c' * 24})
        resumed = ExecutionWorkspace(self.workspace, self.app.state.material_inspections, executor=self.fake, isolated_root=self.store.isolated_root, image='python@sha256:' + 'a' * 64)
        self.addCleanup(resumed.close)
        recovered = resumed.get(self.task_id, proposal['proposal_id'])
        self.assertEqual(recovered['status'], 'interrupted')
        self.assertNotEqual(recovered['qualification']['status'], 'passed')
        approval = {'actor': 'user', 'checkpoint_id': 'resume', 'verified_by': 'agent_bridge_token', 'bridge_token_sha256': hashlib.sha256(TEST_AGENT_BRIDGE_TOKEN.encode()).hexdigest()}
        resumed.start_qualification(self.task_id, proposal['proposal_id'], expected_proposal_sha256=proposal['proposal_sha256'], approval=approval)
        self.assertEqual(self.await_qualification(proposal)['status'], 'qualified')

    def test_goal_revision_invalidates_old_qualification_and_activation(self):
        proposal = self.qualified_proposal()
        changed = self.client.patch(self.base + '/spec', json={'base_revision': self.task['current_spec_revision'], 'business_goal': '用户改变为新定义的约束残差评价目标'})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertGreater(changed.json()['task']['current_spec_revision'], proposal['base_spec_revision'])
        self.assertEqual(self.qualify(proposal).status_code, 409)
        self.assertEqual(self.activate(proposal).status_code, 409)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.client.get(self.base).json()['task']['run_ids'], [])

    def test_activation_requires_passed_digest_and_does_not_approve_contract(self):
        proposal = self.qualified_proposal()
        self.assertEqual(self.activate(proposal, headers={}).status_code, 403)
        self.assertEqual(self.activate(proposal, qualification_sha='0' * 64).status_code, 409)
        response = self.activate(proposal)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['task']['recipe_id'], 'generic-isolated-execution')
        self.assertEqual(result['task']['capability_request']['objective'], 'novel_geometric_constraint_prediction')
        self.assertEqual(result['task']['dataset_id'], proposal['dataset']['dataset_id'])
        self.assertFalse(result['task']['contract_confirmed'])
        self.assertEqual(result['task']['run_ids'], [])
        self.assertEqual(self.client.post(self.base + '/runs', json={}).status_code, 409)
        again = self.activate(proposal)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()['task']['dataset_history'], result['task']['dataset_history'])

    def test_contract_drift_blocks_authorization_without_a_run(self):
        self.activated_proposal()
        confirmation = self.client.post(self.base + '/confirm', json=contract_confirmation_payload(self.client, self.task_id))
        self.assertEqual(confirmation.status_code, 200, confirmation.text)
        path = self.workspace._contract_path(self.task_id)
        contract = read_json(path); contract['execution_spec']['config']['changed_after_approval'] = True
        write_json(path, contract)
        issued = request_task_run_authorization(self.client, self.task_id)
        self.assertEqual(issued.status_code, 409, issued.text)
        self.assertEqual(self.client.get(self.base).json()['task']['run_ids'], [])
        self.assertFalse(any(self.app.state.run_service.runs_dir.glob('*/run_state.json')))

    def test_engineering_projection_preserves_virtual_source_bytes_and_redacts_host_controls(self):
        spec = deepcopy(self.spec)
        code = 'from pathlib import Path\nsource = "/workspace/source/program.py"\ndata = "/workspace/input/train/samples.csv"\noutput = "/workspace/output/model.bin"\n'
        code += 'cache = "/tmp/model-cache"\npython = "/usr/bin/python"\n'
        spec['bundle']['stages']['qualify'] = ['/usr/bin/python', '/workspace/source/program.py', '--cache', '/tmp/model-cache']
        spec['bundle']['files'] = {'program.py': code, 'root': 'literal = "__SMS_VIRTUAL_input__"\n', 'source_path': 'print(1)\n'}
        spec.pop('bundle_sha256')
        spec['config'] = {'host_note': '本机路径/Users/private/source.csv', 'source_path': '/Users/private/source.csv', 'root': 0, 'cwd': False, 'literal': '__SMS_VIRTUAL_output__'}
        spec['inference']['schema'] = {'type': 'object', 'properties': {'root': {'type': 'number'}, 'source_path': {'type': 'string'}, 'cwd': {'type': 'boolean'}}}
        proposal = self.proposal(spec=spec)
        route = f"{self.base}/execution-proposals/{proposal['proposal_id']}"
        local = self.client.get(route).json()['proposal']
        self.assertIn('root', local['dataset'])
        projected = self.client.get(route, headers={'X-Model-Harness-Projection': 'agent-execution-v1'})
        self.assertEqual(projected.status_code, 200, projected.text)
        selected = projected.json()['proposal']
        self.assertEqual(selected['execution_spec']['bundle']['files']['program.py'], code)
        self.assertEqual(selected['execution_spec']['bundle']['files']['root'], 'literal = "__SMS_VIRTUAL_input__"\n')
        self.assertEqual(selected['execution_spec']['bundle']['files']['source_path'], 'print(1)\n')
        from model_harness.isolated_execution import ExecutionBundle
        self.assertEqual(selected['execution_spec']['bundle']['stages']['qualify'], spec['bundle']['stages']['qualify'])
        self.assertEqual(ExecutionBundle.from_dict(selected['execution_spec']['bundle']).digest, selected['execution_spec']['bundle_sha256'])
        self.assertEqual(selected['execution_spec']['inference']['schema'], spec['inference']['schema'])
        self.assertEqual(selected['execution_spec']['config']['root'], 0)
        self.assertIs(selected['execution_spec']['config']['cwd'], False)
        self.assertEqual(selected['execution_spec']['config']['literal'], '__SMS_VIRTUAL_output__')
        self.assertIn('/workspace/source', selected['execution_spec']['bundle']['stages']['train'][1])
        self.assertNotIn('/Users/private', projected.text)
        self.assertNotIn('source_path', selected['execution_spec']['config'])
        self.assertNotIn('root', selected['dataset'])
        ordinary = self.client.get(route, headers={'X-Model-Harness-Projection': 'agent-v1'})
        self.assertNotIn('/workspace/source', ordinary.text)
        payload = {**self.task, 'host_note': '/Users/private/host.txt', 'virtual_note': '/workspace/input/train/sample.csv'}
        with patch.object(self.workspace, 'get_task', return_value=payload):
            outside_engineering = self.client.get(self.base, headers={'X-Model-Harness-Projection': 'agent-execution-v1'})
        self.assertEqual(outside_engineering.status_code, 200)
        self.assertNotIn('/Users/private', outside_engineering.text)
        self.assertNotIn('/workspace/input', outside_engineering.text)

    def test_asset_license_review_flag_is_distinct_from_allow_without_network(self):
        payload = self.root / 'public-weight-fixture.dat'; payload.write_bytes(b'public model fixture bytes')
        revision = 'a' * 40
        approval = {'actor': 'user', 'checkpoint_id': 'asset-download-fixture'}
        for index, license_name in enumerate(['unknown', 'mit', 'cc-by-nc-4.0']):
            metadata = SimpleNamespace(sha=revision, private=False, gated=False,
                siblings=[SimpleNamespace(rfilename='weights.dat', size=payload.stat().st_size, lfs=SimpleNamespace(sha256=sha256_file(payload)))],
                card_data=SimpleNamespace(license=license_name))
            with self.subTest(license=license_name), patch('huggingface_hub.HfApi') as api, patch('huggingface_hub.hf_hub_download', return_value=str(payload)) as download:
                api.return_value.model_info.return_value = metadata
                response = self.client.post(self.base + '/execution-assets', headers=AGENT_BRIDGE_HEADERS,
                    json={'repository': f'fixture/model-{index}', 'revision': revision, 'files': ['weights.dat'], 'approval': approval})
                if license_name == 'cc-by-nc-4.0':
                    self.assertEqual(response.status_code, 409, response.text)
                    download.assert_not_called()
                    continue
                self.assertEqual(response.status_code, 201, response.text)
                asset = response.json()['asset']
                self.assertEqual(asset['license'], license_name)
                self.assertEqual(asset['license_review_required'], license_name == 'unknown')
                self.assertEqual(asset['license_policy']['decision'], 'review' if license_name == 'unknown' else 'allow')
                self.assertFalse(asset['executable_imported_on_host'])
                self.assertEqual(asset['files'][0]['sha256'], sha256_file(payload))
                self.assertEqual(download.call_args.kwargs['revision'], revision)
                self.assertIs(download.call_args.kwargs['token'], False)
        self.assertFalse(self.fake.calls)
        self.assertEqual(self.client.get(self.base).json()['task']['run_ids'], [])

    def test_unknown_objective_uses_one_canonical_authorized_run_with_fixture_transport(self):
        self.activated_proposal()
        confirmed = self.client.post(self.base + '/confirm', json=contract_confirmation_payload(self.client, self.task_id))
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        issued = request_task_run_authorization(self.client, self.task_id)
        self.assertEqual(issued.status_code, 201, issued.text)
        grant = issued.json(); authorization = grant['run_authorization']
        body = {'run_authorization_id': authorization['authorization_id'], 'authorization_token': grant['authorization_token'], 'run_request_sha256': authorization['scope_sha256']}
        bad = dict(body, authorization_token='wrong-token')
        self.assertEqual(self.client.post(self.base + '/runs', json=bad).status_code, 409)
        self.assertEqual(self.client.get(self.base).json()['task']['run_ids'], [])
        response = self.client.post(self.base + '/runs', json=body)
        self.assertEqual(response.status_code, 202, response.text)
        value = response.json()
        run_id = value.get('run_id') or value.get('run', {}).get('run_id') or value.get('task', {}).get('current_run_id')
        self.assertTrue(run_id, value)
        self.app.state.run_service.wait(run_id, timeout=10)
        final = self.app.state.run_service.status(run_id)
        self.assertEqual(final['status'], 'completed', final)
        task = self.client.get(self.base).json()['task']
        self.assertEqual(task['run_ids'], [run_id])
        self.assertEqual(task['current_run_id'], run_id)
        stages = [call['stage'] for call in self.fake.calls]
        self.assertEqual(stages, ['qualify', 'train', 'evaluate'])
        train = next(call for call in self.fake.calls if call['stage'] == 'train')
        evaluate = next(call for call in self.fake.calls if call['stage'] == 'evaluate')
        self.assertFalse(any(key.startswith('test/') for key in train['input_keys']))
        self.assertFalse(any(key.startswith(('train/', 'validation/')) for key in evaluate['input_keys']))
        metrics = read_json(self.app.state.run_service.runs_dir / run_id / 'artifacts' / 'metrics.json')
        self.assertEqual(metrics['split_counts']['test'], 2)
        self.assertEqual(metrics['clean_test']['constraint_violation'], .12)
        self.assertTrue(metrics['gate_checks']['all_offline_gates_passed'])

    def test_discovery_examples_match_actual_stage_consumers_with_fixture_transport(self):
        # Example JSON is transport data only; submitted source is never run.
        from model_harness.plugin_api import RunExecutionContext
        contracts = self.client.get(self.base + '/execution-workspace', headers={
            'X-Model-Harness-Projection': 'agent-execution-v1'}).json()['execution_workspace']['protocol']['stage_result_contracts']
        self.fake.result_overrides = {stage: contract['example'] for stage, contract in contracts.items()}
        self.spec['evaluation'] = {'primary_metric': 'objective_error',
            'gates': {'objective_error': {'operator': 'lte', 'threshold': .2}},
            'minimum_test_samples': 2, 'test_unit': 'independent fixture row'}
        self.activated_proposal()
        confirmed = self.client.post(self.base + '/confirm', json=contract_confirmation_payload(self.client, self.task_id))
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        issued = request_task_run_authorization(self.client, self.task_id)
        self.assertEqual(issued.status_code, 201, issued.text)
        grant = issued.json(); authorization = grant['run_authorization']
        started = self.client.post(self.base + '/runs', json={
            'run_authorization_id': authorization['authorization_id'],
            'authorization_token': grant['authorization_token'], 'run_request_sha256': authorization['scope_sha256']})
        self.assertEqual(started.status_code, 202, started.text)
        task = self.client.get(self.base).json()['task']; run_id = task['current_run_id']
        run_dir = self.app.state.run_service.wait(run_id, timeout=10)
        self.assertEqual(self.app.state.run_service.status(run_id)['status'], 'completed')
        metrics = read_json(run_dir / 'artifacts' / 'metrics.json')
        self.assertEqual(metrics['selected_model'], 'candidate_a')
        self.assertEqual(metrics['clean_test'], {'objective_error': .15})
        sample = self.root / 'fresh.json'; write_json(sample, {'input': 'new fixture'})
        plugin = self.app.state.run_service.registry.get_recipe('generic-isolated-execution')
        prediction = plugin.predict(read_json(run_dir / 'task_contract.json'), model_dir=run_dir / 'artifacts',
            input_files={'sample/fresh.json': sample}, context=RunExecutionContext(self.task_id, run_id, run_dir, self.store.isolated_root))
        self.assertEqual(prediction['prediction'], {'value': .4})
        self.assertEqual([call['stage'] for call in self.fake.calls], ['qualify', 'train', 'evaluate', 'predict'])


if __name__ == '__main__':
    unittest.main()
