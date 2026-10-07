"""A persisted approval is not proof that its old native turn is still live."""
from __future__ import annotations

import unittest
from copy import deepcopy

from model_harness.multi_agent import DshMultiAgentRuntime, HumanCheckpointConflictError
from model_harness.io_utils import read_json
from tests import test_multi_agent_runtime as fixtures


class CheckpointRestartRecoveryTests(unittest.TestCase):
    setUp = fixtures.DshMultiAgentRuntimeTests.setUp
    tearDown = fixtures.DshMultiAgentRuntimeTests.tearDown

    def waiting(self, *, terminal=True):
        session = self.runtime.prompt(self.task_id, '训练', '准备实施')
        team = self.runtime.store.load_team(self.task_id)
        run_id = team['runs'][-1]['run_id']
        self.events.pending[session] = [{'rpc_id': 'restart-rpc', 'kind': 'approval',
            'approval_id': 'restart-approval', 'call_id': 'exact-call',
            'tool_name': 'model_harness_qualify_execution_proposal', 'received_at': 99999}]
        # Exactly the observed race: durable receipt was saved before the tool
        # history projection and therefore has no turn/source sequence yet.
        self.runtime._persist_pending_requested(task_id=self.task_id, team=team, pending=self.runtime._pending(team))
        self.client.sessions[session]['events'] = [
            fixtures.dsh_event(1, 'user/message', {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': f'AGENT_RUN_ID: {run_id}\nUSER_MESSAGE:\n准备实施'}]}),
            fixtures.dsh_event(2, 'tool/call', {'callId': 'exact-call', 'name': 'model_harness_qualify_execution_proposal', 'arguments': {'task_id': self.task_id}}),
        ]
        if terminal:
            self.client.sessions[session]['events'] += [
                fixtures.dsh_event(3, 'tool/result', {'message': {'content': [{'toolCallId': 'exact-call', 'isError': True, 'content': 'interrupted'}]}}),
                fixtures.dsh_event(4, 'turn/end', {'reason': {'kind': 'interrupted'}}),
            ]
        self.client.sessions[session]['running'] = False
        self.runtime = DshMultiAgentRuntime(workspace_root=self.root, client=self.client, events=self.events, cwd=self.root)
        return session, run_id

    def discuss(self):
        return self.runtime.submit_message(self.task_id, '训练', '先解释一下数据准备要求',
            request_id='restart-discussion', checkpoint_rpc_id='restart-rpc')

    def test_cold_completed_call_restores_exact_origin_and_discussion_never_cancels_detached_session(self):
        session, old_run = self.waiting()
        calls_before = len(self.client.calls)
        task_before = read_json(self.task_dir / 'task.json')
        original = self.client.call
        def forbid_cold_cancel(method, payload):
            if method == 'session.cancel':
                raise AssertionError('a detached stopped session must not be cancelled')
            return original(method, payload)
        self.client.call = forbid_cold_cancel
        result = self.discuss()
        self.assertEqual(result['session_id'], session)
        self.assertNotEqual(result['agent_run_id'], old_run)
        self.assertTrue(result['checkpoint_discussion']['previous_checkpoint_terminal_event_id'])
        self.assertEqual(self.client.responses, [])
        self.assertEqual(self.events.pending_for(session), [])
        self.assertEqual(read_json(self.task_dir / 'task.json'), task_before)
        team = self.runtime.store.load_team(self.task_id)
        self.assertEqual(len(team['runs']), 2)
        self.assertEqual(team['runs'][0]['status'], 'failed', 'restart interruption is not reported as a user cancellation')
        self.assertEqual(team['cancellation_targets']['agent_run_ids'], [old_run])
        self.assertFalse(self.runtime.root_context(self.task_id)['control']['stop_automatic_continuations'])
        self.assertFalse(any(method == 'session.cancel' for method, _ in self.client.calls[calls_before:]))
        resolved = [event for event in self.runtime.store.list_events(self.task_id)
            if event.get('payload', {}).get('outcome') == 'invalidated_by_turn_terminal']
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]['call_id'], 'exact-call')
        self.assertEqual(resolved[0]['agent_run_id'], old_run)
        self.assertEqual(resolved[0]['turn_id'], session + ':turn:1')

    def test_other_tab_can_retire_receipt_before_discussion_arrives_without_losing_user_message(self):
        session, old_run = self.waiting()
        observed = self.runtime.conversation(self.task_id)
        self.assertEqual(observed['pending'], [])
        self.assertEqual(self.events.pending_for(session), [])
        result = self.discuss()
        self.assertNotEqual(result['agent_run_id'], old_run)
        self.assertFalse(any(method == 'session.cancel' for method, _ in self.client.calls))
        self.assertEqual(self.client.responses, [])

    def test_quiet_summary_without_exact_terminal_does_not_invent_retirement_or_accept_message(self):
        self.waiting(terminal=False)
        before = len(self.client.calls)
        with self.assertRaises(HumanCheckpointConflictError):
            self.discuss()
        self.assertEqual(len(self.runtime.store.load_team(self.task_id)['runs']), 1)
        self.assertFalse(any(method in {'session.cancel', 'session.prompt'} for method, _ in self.client.calls[before:]))

    def test_retired_checkpoint_cannot_interrupt_a_newer_user_turn(self):
        session, _old_run = self.waiting()
        self.runtime.conversation(self.task_id)
        self.runtime.submit_message(self.task_id, '训练', '新的独立消息', request_id='newer-user-turn')
        before = len(self.client.calls)
        with self.assertRaises(HumanCheckpointConflictError):
            self.discuss()
        self.assertEqual(len(self.runtime.store.load_team(self.task_id)['runs']), 2)
        self.assertFalse(any(method in {'session.cancel', 'session.prompt'} for method, _ in self.client.calls[before:]))

    def test_live_handoff_fences_native_continuations_before_cancel_but_not_new_user_run(self):
        session, old_run = self.waiting(terminal=False)
        self.client.sessions[session]['running'] = True
        original = self.client.call
        observed = []
        def rpc(method, payload):
            if method in {'session.cancel', 'session.prompt'}:
                observed.append((method, self.runtime.root_context(self.task_id)['control']['stop_automatic_continuations']))
            return original(method, payload)
        self.client.call = rpc
        self.discuss()
        self.assertEqual(observed, [('session.cancel', True), ('session.prompt', False)])
        self.assertEqual(self.runtime.store.load_team(self.task_id)['cancellation_targets']['agent_run_ids'], [old_run])
        self.assertEqual(self.client.responses, [])


if __name__ == '__main__':
    unittest.main()
