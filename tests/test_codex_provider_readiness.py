import os
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from model_harness.multi_agent import DshMultiAgentRuntime


class ProviderClient:
    def __init__(self, active=True):
        self.active = active
        self.calls = []

    def call(self, method, params):
        self.calls.append(method)
        if method != "llm.providers":
            raise AssertionError("Codex readiness must not resolve API credentials")
        return {"providers": [{"provider": "codex-cli", "active": self.active}]}


class CodexProviderReadinessTests(unittest.TestCase):
    def runtime(self, active=True):
        runtime = object.__new__(DshMultiAgentRuntime)
        runtime.client = ProviderClient(active)
        return runtime

    @patch.dict(os.environ, {"MODEL_HARNESS_AGENT_PROVIDER": "codex-cli", "MODEL_HARNESS_CODEX_BIN": "/trusted/codex", "OPENAI_API_KEY": "private", "DEEPSEEK_API_KEY": "private"})
    def test_chatgpt_login_ready_without_api_credentials_and_cached(self):
        runtime = self.runtime()
        with patch("model_harness.multi_agent.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="Logged in using ChatGPT")) as run:
            first = runtime._provider_readiness(transport_ready=True)
            second = runtime._provider_readiness(transport_ready=True)
        self.assertTrue(first["ready"])
        self.assertEqual(first["provider"], "codex-cli")
        self.assertEqual(first["source"], "chatgpt_login")
        self.assertEqual(first, second)
        self.assertEqual(run.call_count, 1)
        self.assertNotIn("OPENAI_API_KEY", run.call_args.kwargs["env"])
        self.assertNotIn("DEEPSEEK_API_KEY", run.call_args.kwargs["env"])
        self.assertEqual(runtime.client.calls, ["llm.providers", "llm.providers"])

    @patch.dict(os.environ, {"MODEL_HARNESS_AGENT_PROVIDER": "codex-cli", "MODEL_HARNESS_CODEX_BIN": "/trusted/codex"})
    def test_api_login_or_timeout_cannot_be_called_chatgpt_plan_ready(self):
        for observed in (SimpleNamespace(returncode=0, stdout="Logged in using an API key", stderr=""), subprocess.TimeoutExpired("codex", 8)):
            runtime = self.runtime()
            with patch("model_harness.multi_agent.subprocess.run", side_effect=observed if isinstance(observed, Exception) else None, return_value=observed):
                result = runtime._provider_readiness(transport_ready=True)
            self.assertFalse(result["ready"])
            self.assertEqual(result["reason"], "codex_chatgpt_login_required")

    @patch.dict(os.environ, {"MODEL_HARNESS_AGENT_PROVIDER": "codex-cli", "MODEL_HARNESS_CODEX_BIN": "/trusted/codex"})
    def test_active_login_without_registered_route_is_not_ready(self):
        runtime = self.runtime(active=False)
        with patch("model_harness.multi_agent.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="Logged in using ChatGPT", stderr="")):
            result = runtime._provider_readiness(transport_ready=True)
        self.assertFalse(result["ready"])
        self.assertEqual(result["reason"], "llm_provider_inactive")

    @patch.dict(os.environ, {"MODEL_HARNESS_AGENT_PROVIDER": "codex-cli"})
    def test_transport_failure_does_not_start_login_probe(self):
        with patch("model_harness.multi_agent.subprocess.run") as run:
            self.assertFalse(self.runtime()._provider_readiness(transport_ready=False)["ready"])
        run.assert_not_called()

    @patch.dict(os.environ, {"MODEL_HARNESS_AGENT_PROVIDER": "codex-cli"})
    def test_cold_root_model_is_selected_before_new_turn_not_child_or_running_root(self):
        calls = []
        runtime = object.__new__(DshMultiAgentRuntime)
        state = {"running": False}
        def call(method, params):
            calls.append((method, params))
            return {"items": [{"sessionId": "root-owned", "running": state["running"]}]} if method == "session.list" else {"selected": params}
        runtime.client = SimpleNamespace(call=call)
        runtime._select_configured_model_for_idle_root({"root_session_id": "root-owned"})
        self.assertEqual(calls[-1], ("session.selectModel", {"sessionId": "root-owned", "provider": "codex-cli", "model": "gpt-5.6-sol", "reasoningEffort": "low"}))
        state["running"] = True; calls.clear()
        runtime._select_configured_model_for_idle_root({"root_session_id": "root-owned"})
        self.assertEqual([method for method, _ in calls], ["session.list"])


if __name__ == "__main__":
    unittest.main()
