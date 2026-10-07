"""Recover observed history without treating a stale snapshot as live authority."""
from __future__ import annotations

import unittest
from copy import deepcopy
from unittest.mock import patch

from model_harness.multi_agent import DshMultiAgentRuntime, HumanCheckpointConflictError, MultiAgentRuntimeError
from tests import test_multi_agent_runtime as fixtures


class ConversationOfflineRecoveryTests(unittest.TestCase):
    setUp = fixtures.DshMultiAgentRuntimeTests.setUp
    tearDown = fixtures.DshMultiAgentRuntimeTests.tearDown
    _latest_agent_run_id = fixtures.DshMultiAgentRuntimeTests._latest_agent_run_id
    _root_history_with_candidate = fixtures.DshMultiAgentRuntimeTests._root_history_with_candidate

    def prime(self):
        session = self.runtime.prompt(self.task_id, '目标', '检查任务状态后继续')
        history = self._root_history_with_candidate(run_id=self._latest_agent_run_id(),
            tool_name='model_harness_get_task', result={'task': self.task},
            candidate_text='已经读取了你的任务；接下来检查材料。')
        self.client.sessions[session]['events'] = history
        return session, self.runtime.conversation(self.task_id)

    def assert_degraded_history(self, value, previous):
        self.assertEqual(value['observation_source'], 'persisted_projection')
        self.assertEqual(value['projection_health'], 'observation_degraded')
        self.assertFalse(value['execution_state_observed'])
        self.assertEqual(value['interaction_projection']['phase'], 'observation_degraded')
        self.assertIsNone(value['interaction_projection']['terminal_outcome'])
        self.assertIsNone(value['agent_response_running'])
        self.assertEqual(value['pending'], [])
        self.assertEqual(value['human_checkpoints'], [])
        self.assertFalse(value['can_cancel_agent'])
        self.assertFalse(value['interaction_projection']['can_cancel'])
        self.assertEqual([row['event_id'] for row in value['items']], [row['event_id'] for row in previous['items']])
        self.assertEqual([row['action_id'] for row in value['actions']], [row['action_id'] for row in previous['actions']])
        self.assertEqual([row['run_id'] for row in value['runs']], [row['run_id'] for row in previous['runs']])
        self.assertTrue(all(row['observation_stale'] for row in value['items']))
        self.assertTrue(all(row['response_running'] is None for row in value['agent_turns']))

    def test_rpc_failure_keeps_message_action_run_identities_without_reconciling_or_writing(self):
        _, previous = self.prime()
        paths = [self.runtime.store._team_path(self.task_id), self.runtime.store._events_path(self.task_id)]
        before = [path.read_bytes() for path in paths]
        for failed_method in ('session.history', 'session.list'):
            self.client.fail_methods = {failed_method}
            with self.subTest(failed_method=failed_method), patch.object(self.runtime, '_reconcile_team', side_effect=AssertionError('offline history must not reconcile current state')):
                value = self.runtime.conversation(self.task_id)
                self.assert_degraded_history(value, previous)
                self.assertIsNone(value['running'])
                self.assertIsNone(value['execution_running'])
                self.assertEqual([path.read_bytes() for path in paths], before)

    def test_fresh_runtime_recovers_persisted_history_while_disconnected_without_rpc(self):
        _, previous = self.prime()
        disconnected = fixtures.FakeDshClient(available=False)
        recovered = DshMultiAgentRuntime(workspace_root=self.root, client=disconnected,
            events=fixtures.FakeEventHub(), cwd=self.root)
        value = recovered.conversation(self.task_id)
        self.assert_degraded_history(value, previous)
        self.assertEqual(disconnected.calls, [])
        with self.assertRaises(MultiAgentRuntimeError):
            recovered.conversation('another-task')

    def test_stale_native_approval_is_not_actionable_until_successful_live_refresh(self):
        session, _ = self.prime()
        self.events.pending[session] = [{'kind': 'approval', 'rpc_id': 'native-recovery-approval',
            'approval_id': 'approval-original', 'received_at': 1}]
        before = self.runtime.conversation(self.task_id)
        self.assertEqual(len(before['pending']), 1)
        self.client.fail_methods = {'session.history'}
        value = self.runtime.conversation(self.task_id)
        self.assert_degraded_history(value, before)
        self.assertTrue(all(row.get('actionable') is False for row in value['items']
            if row.get('event_type') in {'question', 'approval'}))
        # session.list is still reachable: it must not bypass the failed history
        # observation or submit the cached approval from another browser tab.
        with self.assertRaises(HumanCheckpointConflictError):
            self.runtime.answer_approval(self.task_id, 'native-recovery-approval', 'allow_once')
        self.assertEqual(self.client.responses, [])
        self.client.fail_methods = set()
        healthy = self.runtime.conversation(self.task_id)
        self.assertEqual(healthy['projection_health'], 'healthy')
        self.assertNotIn('observation_source', healthy)
        self.assertEqual(len(healthy['pending']), 1)
        self.runtime.answer_approval(self.task_id, 'native-recovery-approval', 'allow_once')
        self.assertEqual(len(self.client.responses), 1)

    def test_independently_observed_training_run_stays_visible_without_claiming_agent_activity(self):
        _, previous = self.prime()
        action = {'task_id': self.task_id, 'action_id': 'training-run:actual',
            'action_type': 'training_run', 'run_id': 'actual-run', 'status': 'running',
            'running': True, 'worker_running': True}
        self.runtime.background_actions_provider = lambda owner: [deepcopy(action)]
        self.client.fail_methods = {'session.history'}
        value = self.runtime.conversation(self.task_id)
        self.assert_degraded_history(value, previous)
        self.assertTrue(value['execution_running'])
        self.assertTrue(value['background_action_running'])
        self.assertTrue(value['training_runs'][0]['running'])
        self.assertEqual(value['training_runs'][0]['training_run_id'], 'actual-run')
        self.assertEqual(value['background_actions'], [action])


if __name__ == '__main__':
    unittest.main()
