from __future__ import annotations

import json
import subprocess
import unittest
from copy import deepcopy
from unittest.mock import patch

from model_harness.errors import ContractError, HarnessError
from model_harness.execution_workspace import seal
from model_harness.io_utils import read_json, write_json
from tests import test_execution_workspace as fixtures


class ExecutionAuthorizationScopeTests(unittest.TestCase):
    setUp = fixtures.ExecutionWorkspaceTests.setUp
    create_proposal = fixtures.ExecutionWorkspaceTests.create_proposal
    proposal = fixtures.ExecutionWorkspaceTests.proposal
    qualify = fixtures.ExecutionWorkspaceTests.qualify
    await_qualification = fixtures.ExecutionWorkspaceTests.await_qualification
    qualified_proposal = fixtures.ExecutionWorkspaceTests.qualified_proposal
    activate = fixtures.ExecutionWorkspaceTests.activate
    activated_proposal = fixtures.ExecutionWorkspaceTests.activated_proposal

    def test_binding_must_name_the_exact_qualification_and_base_revision(self):
        self.activated_proposal()
        contract = read_json(self.workspace._contract_path(self.task_id))
        self.store.authorize_contract(self.task_id, contract)
        for field, value in [('qualification_id', 'foreign-qualification'), ('base_spec_revision', 999)]:
            changed = deepcopy(contract)
            changed['execution_binding'][field] = value
            with self.subTest(field=field), self.assertRaises(HarnessError):
                self.store.authorize_contract(self.task_id, changed)

    def test_resealed_foreign_qualification_cannot_activate_even_with_matching_hash(self):
        proposal = self.qualified_proposal()
        original = proposal['qualification']
        path = self.store._dir(self.task_id, proposal['proposal_id']) / 'qualifications' / original['qualification_id'] / 'qualification.json'
        original = read_json(path)
        for field, value in [('task_id', 'foreign-task'), ('proposal_id', 'execution-' + 'f' * 24), ('proposal_sha256', '0' * 64)]:
            changed = seal({**original, field: value}, 'qualification_sha256')
            write_json(path, changed)
            found = self.store.get(self.task_id, proposal['proposal_id'])
            with self.subTest(field=field):
                response = self.activate(found)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertFalse((path.parent.parent.parent / 'activation.json').exists())
        write_json(path, original)
        self.assertEqual(self.activate(proposal).status_code, 200)

    def test_resealed_activation_for_a_different_proposal_cannot_authorize_run(self):
        result = self.activated_proposal()
        proposal = result['proposal']
        path = self.store._dir(self.task_id, proposal['proposal_id']) / 'activation.json'
        original = read_json(path)
        write_json(path, seal({**original, 'proposal_id': 'execution-' + 'e' * 24}, 'activation_sha256'))
        with self.assertRaises(ContractError):
            self.store.authorize_contract(self.task_id, read_json(self.workspace._contract_path(self.task_id)))

    def test_runtime_image_readiness_is_readonly_and_checks_exact_immutable_identity(self):
        image_id = 'sha256:' + 'd' * 64
        self.store.image = image_id
        with patch.object(self.store, 'list', side_effect=AssertionError('must not scan proposals')), \
                patch.object(self.store.materials, 'list', side_effect=AssertionError('must not scan materials')):
            for observed, code, expected in [({}, 0, False), ({'id': 'sha256:' + 'c' * 64}, 0, False), ({'id': image_id}, 0, True), ({'id': image_id}, 1, False)]:
                with self.subTest(observed=observed, code=code), patch.object(self.fake, '_query', return_value=subprocess.CompletedProcess([], code, json.dumps(observed).encode(), b'')) as query:
                    result = self.client.get('/runtime').json()
                    self.assertEqual(result['byom_execution_available'], expected)
                    self.assertEqual(result['execution_image']['ready'], expected)
                    self.assertTrue(result['isolation_runtime']['available'])
                    self.assertEqual(query.call_args.args[0][1:3], ['image', 'inspect'])
                    self.assertEqual(self.fake.calls, [])
            self.store.image = 'repository@sha256:' + 'a' * 64
            for digests, expected in [(['repository@sha256:' + 'b' * 64], False), ([self.store.image], True)]:
                with patch.object(self.fake, '_query', return_value=subprocess.CompletedProcess([], 0, json.dumps({'id': image_id, 'repo_digests': digests}).encode(), b'')):
                    self.assertEqual(self.store.runtime_readiness()['ready'], expected)
            self.store.image = 'repository:latest'
            with patch.object(self.fake, '_query', side_effect=AssertionError('mutable images must not be inspected')):
                self.assertFalse(self.store.runtime_readiness()['ready'])


if __name__ == '__main__':
    unittest.main()
