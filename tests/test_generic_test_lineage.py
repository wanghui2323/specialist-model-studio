from __future__ import annotations

import unittest
from copy import deepcopy
from uuid import uuid4

from model_harness.errors import ContractError
from model_harness.generic_data import create_generic_dataset
from model_harness.generic_protocol import validate_execution_spec
from model_harness.io_utils import read_json, write_json
from model_harness.material_inspection import MaterialInspectionStore
from model_harness.runner import execute_run, prepare_run
from tests import test_generic_recipe as fixtures
from tests import test_execution_workspace as workspace_fixtures
from tests.contract_confirmation import contract_confirmation_payload
from tests.run_authorization import request_task_run_authorization


class GenericTestLineageTests(unittest.TestCase):
    setUp = fixtures.GenericRecipeTests.setUp
    context = fixtures.GenericRecipeTests.context
    run_fixture = fixtures.GenericRecipeTests.run_fixture

    def metrics(self, run):
        return read_json(run / 'artifacts/metrics.json')

    def replace_dataset(self, *, filename='renamed.csv', test_indices=None, offset=0):
        materials = MaterialInspectionStore(self.root / 'workspace')
        content = 'left,right,target\n' + ''.join(f'{i + offset},{i + offset + 2},{2 * (i + offset) - .5}\n' for i in range(80))
        receipt, _ = materials.upload(self.owner, content.encode(), filename, 'replacement-' + filename)
        mapping = [{'material_id': receipt['material_id'], 'inspection_sha256': receipt['inspection_sha256'], 'split': split, 'csv_rows': indices}
            for split, indices in [('train', list(range(30))), ('validation', list(range(30, 40))), ('test', test_indices or list(range(40, 60)))]]
        imported = create_generic_dataset(self.task_dir / 'execution_proposals' / ('replacement-' + filename), materials, self.owner, mapping)
        self.contract['dataset'] = imported.contract_dataset
        self.contract['execution_spec']['data_mapping'] = mapping
        self.contract['execution_spec']['bundle']['files']['unseen.py'] += '# A different proposed implementation\n'
        self.contract['execution_spec'].pop('bundle_sha256', None)
        self.contract['execution_spec'] = validate_execution_spec(self.contract['execution_spec'])

    def test_new_proposal_and_upload_name_cannot_reset_a_previously_evaluated_holdout(self):
        first = self.run_fixture()
        old_files = {path.relative_to(first).as_posix(): path.read_bytes() for path in first.rglob('*') if path.is_file()}
        old_test_hash = self.contract['dataset']['splits']['test'][0]['sha256']
        self.replace_dataset()
        self.assertEqual(self.contract['dataset']['splits']['test'][0]['sha256'], old_test_hash)
        second = self.run_fixture()
        self.assertFalse(self.metrics(first)['test_contaminated'])
        metrics = self.metrics(second)
        self.assertTrue(metrics['test_contaminated'])
        self.assertEqual(metrics['test_lineage']['prior_run_ids'], [first.name])
        self.assertEqual(metrics['contamination_reasons'], ['final_test_content_previously_exposed_to_evaluation'])
        self.assertTrue(metrics['gate_checks']['all_offline_gates_passed'], 'quality thresholds are unchanged')
        report = read_json(second / 'evidence/evaluation_report.json')
        self.assertFalse(report['release_ready'])
        self.assertEqual(report['conclusion'], 'insufficient_evidence')
        self.assertEqual(old_files, {path.relative_to(first).as_posix(): path.read_bytes() for path in first.rglob('*') if path.is_file()})

    def test_regrouped_partially_reused_csv_rows_are_not_fresh_test_content(self):
        first = self.run_fixture()
        old_test_hash = self.contract['dataset']['splits']['test'][0]['sha256']
        self.replace_dataset(test_indices=list(range(55, 75)))
        self.assertNotEqual(self.contract['dataset']['splits']['test'][0]['sha256'], old_test_hash)
        second = self.run_fixture()
        lineage = self.metrics(second)['test_lineage']
        self.assertTrue(lineage['test_contaminated'])
        self.assertEqual(lineage['prior_run_ids'], [first.name])
        self.assertEqual(lineage['overlaps'][0]['overlapping_content_identity_count'], 5)

    def test_genuinely_new_holdout_content_can_remain_independent(self):
        self.run_fixture()
        self.replace_dataset(test_indices=list(range(60, 80)))
        second = self.run_fixture()
        self.assertFalse(self.metrics(second)['test_contaminated'])
        self.assertEqual(self.metrics(second)['test_lineage']['prior_run_ids'], [])
        self.assertTrue(read_json(second / 'evidence/evaluation_report.json')['release_ready'])

    def test_train_only_failure_and_qualification_did_not_expose_the_test_split(self):
        self.plugin.qualify(self.contract, self.context('qualification-only'))
        failed = prepare_run(self.contract, self.root / 'runs', registry=self.registry)
        self.executor.statuses['train'] = 'failed'
        with self.assertRaises(ContractError):
            execute_run(failed, registry=self.registry)
        self.executor.statuses.clear()
        second = self.run_fixture()
        self.assertFalse(self.metrics(second)['test_contaminated'])
        self.assertTrue(read_json(second / 'evidence/evaluation_report.json')['release_ready'])

    def test_failed_evaluate_that_received_test_bytes_still_exposes_them(self):
        failed = prepare_run(self.contract, self.root / 'runs', registry=self.registry)
        self.executor.statuses['evaluate'] = 'failed'
        with self.assertRaises(ContractError):
            execute_run(failed, registry=self.registry)
        self.executor.statuses.clear()
        second = self.run_fixture()
        self.assertTrue(self.metrics(second)['test_contaminated'])
        self.assertEqual(self.metrics(second)['test_lineage']['prior_run_ids'], [failed.name])

    def test_foreign_task_evaluation_is_not_this_tasks_lineage(self):
        original = self.contract['task_id']
        self.contract['task_id'] = 'task-unrelated-owner'
        self.run_fixture()
        self.contract['task_id'] = original
        second = self.run_fixture()
        self.assertFalse(self.metrics(second)['test_contaminated'])

    def test_tampered_prior_evaluate_evidence_fails_closed_instead_of_clearing_lineage(self):
        first = self.run_fixture()
        path = next(path for path in (first / 'evidence/isolated_stages').glob('*.json') if read_json(path)['execution']['stage'] == 'evaluate')
        value = read_json(path)
        value['execution']['inputs'][0]['sha256'] = '0' * 64
        write_json(path, value)
        second = prepare_run(self.contract, self.root / 'runs', registry=self.registry)
        with self.assertRaisesRegex(ContractError, 'identity or digest'):
            execute_run(second, registry=self.registry)
        self.assertFalse((second / 'artifacts/metrics.json').exists())
        self.assertEqual(read_json(second / 'run_state.json')['status'], 'failed')


class WorkspaceTestLineageTests(unittest.TestCase):
    setUp = workspace_fixtures.ExecutionWorkspaceTests.setUp
    create_proposal = workspace_fixtures.ExecutionWorkspaceTests.create_proposal
    proposal = workspace_fixtures.ExecutionWorkspaceTests.proposal
    qualify = workspace_fixtures.ExecutionWorkspaceTests.qualify
    await_qualification = workspace_fixtures.ExecutionWorkspaceTests.await_qualification
    qualified_proposal = workspace_fixtures.ExecutionWorkspaceTests.qualified_proposal
    activate = workspace_fixtures.ExecutionWorkspaceTests.activate
    activated_proposal = workspace_fixtures.ExecutionWorkspaceTests.activated_proposal

    def start_approved_run(self):
        confirmed = self.client.post(self.base + '/confirm', json=contract_confirmation_payload(self.client, self.task_id))
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        issued = request_task_run_authorization(self.client, self.task_id, checkpoint_id='native-lineage-run-' + uuid4().hex)
        self.assertEqual(issued.status_code, 201, issued.text)
        grant = issued.json(); authorization = grant['run_authorization']
        response = self.client.post(self.base + '/runs', json={'run_authorization_id': authorization['authorization_id'],
            'authorization_token': grant['authorization_token'], 'run_request_sha256': authorization['scope_sha256']})
        self.assertEqual(response.status_code, 202, response.text)
        value = response.json()
        run_id = value.get('run_id') or value.get('run', {}).get('run_id') or value.get('task', {}).get('current_run_id')
        self.app.state.run_service.wait(run_id, timeout=10)
        self.assertEqual(self.app.state.run_service.status(run_id)['status'], 'completed')
        observed = self.client.get(self.base)
        self.assertEqual(observed.status_code, 200, observed.text)
        self.assertNotEqual(observed.json()['task']['status'], 'running')
        return self.app.state.run_service.runs_dir / run_id

    def test_two_separately_qualified_activated_approved_proposals_share_final_test_lineage(self):
        first_proposal = self.activated_proposal()['proposal']
        first = self.start_approved_run()
        changed = deepcopy(self.spec)
        changed['config']['new_hyperparameter'] = 2
        second_proposal = self.proposal(request='another-engineering-version', spec=changed)
        self.assertNotEqual(first_proposal['proposal_sha256'], second_proposal['proposal_sha256'])
        self.assertEqual(self.qualify(second_proposal).status_code, 202)
        self.assertEqual(self.activate(self.await_qualification(second_proposal)).status_code, 200)
        second = self.start_approved_run()
        self.assertFalse(read_json(first / 'artifacts/metrics.json')['test_contaminated'])
        metrics = read_json(second / 'artifacts/metrics.json')
        self.assertTrue(metrics['test_contaminated'])
        self.assertEqual(metrics['test_lineage']['prior_run_ids'], [first.name])
        self.assertEqual(metrics['test_lineage']['overlaps'][0]['proposal_id'], first_proposal['proposal_id'])
        self.assertFalse(read_json(second / 'evidence/evaluation_report.json')['release_ready'])


if __name__ == '__main__':
    unittest.main()
