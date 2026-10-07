import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from model_harness.multi_agent import DshMultiAgentRuntime


class GenericProviderReadinessTests(unittest.TestCase):
    def runtime(self, active=True, configured=True):
        runtime = object.__new__(DshMultiAgentRuntime)
        runtime.calls = []
        def call(method, params):
            runtime.calls.append((method, params))
            if method == 'llm.providers': return {'providers':[{'provider':'custom-model-service','active':active}]}
            if method == 'credentials.describe': return {'credentials':{'SELECTED_SERVICE_KEY':{'configured':configured,'source':'environment'}}}
            if method == 'session.list': return {'items':[{'sessionId':'root-owned','running':False}]}
            if method == 'session.selectModel': return {'selected':params}
            raise AssertionError('must not read credentials or execute a model probe')
        runtime.client = SimpleNamespace(call=call)
        return runtime

    @patch.dict(os.environ, {'MODEL_HARNESS_AGENT_PROVIDER':'custom-model-service','MODEL_HARNESS_AGENT_MODEL':'custom-small-model','MODEL_HARNESS_AGENT_CREDENTIAL_REF':'SELECTED_SERVICE_KEY'}, clear=True)
    def test_registered_custom_provider_uses_its_own_credential_description(self):
        runtime = self.runtime()
        result = runtime._provider_readiness(transport_ready=True)
        self.assertTrue(result['ready'])
        self.assertEqual(runtime.calls[-1], ('credentials.describe',{'refs':['SELECTED_SERVICE_KEY']}))
        self.assertNotIn('DEEPSEEK_API_KEY',str(runtime.calls))

    @patch.dict(os.environ, {'MODEL_HARNESS_AGENT_PROVIDER':'custom-model-service','MODEL_HARNESS_AGENT_MODEL':'custom-small-model','MODEL_HARNESS_AGENT_AUTH':'none'}, clear=True)
    def test_explicit_local_no_auth_route_still_requires_registered_active_adapter(self):
        for active in (True,False):
            runtime = self.runtime(active=active)
            result = runtime._provider_readiness(transport_ready=True)
            self.assertEqual(result['ready'],active)
            self.assertEqual([m for m,_ in runtime.calls],['llm.providers'])

    @patch.dict(os.environ, {'MODEL_HARNESS_AGENT_PROVIDER':'custom-model-service','MODEL_HARNESS_AGENT_MODEL':'custom-small-model'}, clear=True)
    def test_no_vendor_credential_is_guessed_for_another_provider(self):
        result = self.runtime()._provider_readiness(transport_ready=True)
        self.assertFalse(result['ready'])
        self.assertEqual(result['reason'],'llm_credential_reference_missing')

    @patch.dict(os.environ, {'MODEL_HARNESS_AGENT_PROVIDER':'custom-model-service','MODEL_HARNESS_AGENT_AUTH':'none'}, clear=True)
    def test_missing_model_is_not_ready(self):
        result = self.runtime()._provider_readiness(transport_ready=True)
        self.assertFalse(result['ready'])
        self.assertEqual(result['reason'],'llm_model_selection_missing')

    @patch.dict(os.environ, {'MODEL_HARNESS_AGENT_PROVIDER':'custom-model-service','MODEL_HARNESS_AGENT_MODEL':'custom-small-model'}, clear=True)
    def test_cold_root_uses_configured_provider_without_forcing_codex_model_or_effort(self):
        runtime = self.runtime()
        runtime._select_configured_model_for_idle_root({'root_session_id':'root-owned'})
        self.assertEqual(runtime.calls[-1],('session.selectModel',{'sessionId':'root-owned','provider':'custom-model-service','model':'custom-small-model'}))


if __name__=='__main__': unittest.main()
