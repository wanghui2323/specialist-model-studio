"""Raw token count must not multiply discarded identity/hash work."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from model_harness.multi_agent import DshConversationV2Projector
from tests import test_multi_agent_runtime as fixtures


class ConversationProjectionCostTests(unittest.TestCase):
    setUp = fixtures.DshMultiAgentRuntimeTests.setUp
    tearDown = fixtures.DshMultiAgentRuntimeTests.tearDown
    _latest_agent_run_id = fixtures.DshMultiAgentRuntimeTests._latest_agent_run_id
    _root_history_with_candidate = fixtures.DshMultiAgentRuntimeTests._root_history_with_candidate

    def test_discarded_chunks_never_enter_hash_or_identity_work_and_messages_stay_lossless(self):
        self.runtime.prompt(self.task_id, '投影', '读取完整状态')
        team = self.runtime.store.load_team(self.task_id)
        retained = self._root_history_with_candidate(run_id=self._latest_agent_run_id(), tool_name='model_harness_get_task',
            result={'task': self.task}, candidate_text='需要保留的原始消息和工具回执')
        retained.append(fixtures.dsh_event(8, 'turn/end', {'reason': {'kind': 'completed'}}))
        projector = DshConversationV2Projector()
        expected = projector.project(task_id=self.task_id, team=team, history={'events': retained})
        chunks = [fixtures.dsh_event(100 + index, 'assistant/chunk', {'chunk': {'type': 'text-delta', 'text': 'token'},
            'agentId': 'untrusted-role-that-must-not-be-observed'}) for index in range(25_000)]
        noisy = [retained[0], *chunks, *retained[1:]]
        with patch.object(projector, '_source_key', wraps=projector._source_key) as hashes, \
                patch.object(projector, '_agent_identity', wraps=projector._agent_identity) as identities:
            result = projector.project(task_id=self.task_id, team=team, history={'events': noisy})
        self.assertEqual(result, expected)
        self.assertEqual(hashes.call_count, len(retained))
        self.assertEqual(identities.call_count, len(retained))

    def test_child_turn_start_and_invocation_scope_survive_early_noise_filter(self):
        self.runtime.prompt(self.task_id, '投影', '委派并保留身份')
        team = self.runtime.store.load_team(self.task_id)
        run_id = self._latest_agent_run_id()
        child = 'native-child'; agent = 'data_preparation'
        team['delegations']['native-call'] = {'delegation_id': 'native-call', 'agent_run_id': run_id,
            'dsh_session_id': child, 'target_agent_id': agent, 'source_agent_id': team['root_agent_id'],
            'parent_delegation_id': None, 'lineage_verified': True, 'lineage_origin': 'subagent',
            'lineage_parent_session_id': team['root_session_id']}
        retained = [fixtures.dsh_event(1, 'turn/start', {'turn': 9}),
            fixtures.dsh_event(3, 'tool/call', {'callId': 'read-material', 'name': 'model_harness_get_task', 'input': {'task_id': self.task_id}}),
            fixtures.dsh_event(4, 'tool/result', {'message': {'content': [{'toolCallId': 'read-material', 'content': {'task': self.task}, 'isError': False}]}}),
            fixtures.dsh_event(5, 'assistant/message', {'message': {'content': [{'type': 'text', 'text': '真实子任务结果'}]}}),
            fixtures.dsh_event(6, 'turn/end', {'reason': {'kind': 'completed'}})]
        projector = DshConversationV2Projector()
        args = {'task_id': self.task_id, 'team': team, 'session_id': child, 'session_agent_id': agent}
        expected = projector.project(**args, history={'events': retained})
        noise = [fixtures.dsh_event(2, 'assistant/chunk', {'chunk': {'text': 'discarded'}})] * 25_000
        with patch.object(projector, '_verified_child_projection_identity', wraps=projector._verified_child_projection_identity) as identities:
            found = projector.project(**args, history={'events': [retained[0], *noise, *retained[1:]]})
        self.assertEqual(found, expected)
        self.assertEqual(identities.call_count, 5, 'one initial binding plus four meaningful events, independent of token count')
        self.assertTrue(found)
        self.assertTrue(all(row['turn_id'] == child + ':turn:9' for row in found))
        self.assertTrue(all(row['agent_run_id'] == run_id and row['delegation_id'] == 'native-call' for row in found))


if __name__ == '__main__':
    unittest.main()
