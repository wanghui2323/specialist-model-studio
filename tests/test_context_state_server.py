import base64
import hashlib
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch
from fastapi.testclient import TestClient
from model_harness.server import create_app
from test_multi_agent_runtime import FakeDshClient


class ContextStateServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        with patch.dict('os.environ',{'MODEL_HARNESS_AGENT_BRIDGE_TOKEN':'context-test-channel'}):self.app=create_app(self.tmp.name)
        self.runtime=self.app.state.conversation_runtime;self.runtime.client=FakeDshClient()
        self.patches=[patch.object(self.runtime,'start'),patch.object(self.runtime,'stop')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.client=TestClient(self.app);self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        self.owner=self.client.post('/tasks',json={'name':'新目标','business_goal':'训练未知传感器的小模型'}).json()['task']['task_id']
        self.runtime.submit_message(self.owner,'目标','我已经决定从零训练，预算不能增加。',request_id='source-1')
        self.root=self.runtime.store.load_team(self.owner)['root_session_id']

    def body(self):
        state=self.client.get(f'/conversations/{self.owner}/context-state').json()['context_state']
        return {'base_revision':state['revision'],'update_id':'update-1','entries':[{'slot':'training_route','kind':'user_explicit','value':'from_scratch','source_request_id':'source-1','quote':'已经决定从零训练'}],'provenance':{'session_id':self.root,'call_id':'call-1'}}

    def test_metadata_update_requires_bridge_and_exact_owner_root_but_does_not_change_task(self):
        before=self.client.get(f'/tasks/{self.owner}').json()['task'];body=self.body()
        self.assertEqual(self.client.post(f'/conversations/{self.owner}/context-state',json=body).status_code,403)
        headers={'X-Model-Harness-Agent-Token':'context-test-channel'}
        foreign=deepcopy(body);foreign['provenance']['session_id']='foreign'
        self.assertEqual(self.client.post(f'/conversations/{self.owner}/context-state',json=foreign,headers=headers).status_code,409)
        response=self.client.post(f'/conversations/{self.owner}/context-state',json=body,headers=headers)
        self.assertEqual(response.status_code,200);self.assertFalse(response.json()['context_state']['grants_execution_authorization'])
        self.assertEqual(self.client.get(f'/tasks/{self.owner}').json()['task'],before)
        self.assertEqual(self.runtime.root_context(self.owner)['conversation_state']['entries'][0]['value'],'from_scratch')

    def test_raw_message_range_is_owned_and_declares_completeness(self):
        path=f'/conversations/{self.owner}/context-evidence?kind=message&object_id=source-1&max_chars=4'
        response=self.client.get(path);self.assertEqual(response.status_code,200)
        value=response.json()['evidence'];self.assertFalse(value['complete']);self.assertTrue(value['has_more']);self.assertEqual(value['text'],'我已经决')
        self.assertEqual(self.client.get(path.replace('source-1','unobserved')).status_code,404)

    def test_source_reader_uses_frozen_file_map_not_host_paths_and_preserves_exact_code(self):
        code='from pathlib import Path\nvalue="/Users/private/literal"\nprint("中文")\n'
        proposal_id='execution-'+'a'*24
        record={'task_id':self.owner,'proposal_id':proposal_id,'proposal_sha256':'b'*64,'execution_spec':{'bundle':{'files':{'src/run.py':code}}}}
        with patch.object(self.app.state.execution_workspace,'get',return_value=record) as get:
            response=self.client.get(f'/conversations/{self.owner}/context-evidence',params={'kind':'execution_source','object_id':proposal_id,'filename':'src/run.py','start':0,'max_chars':8000},headers={'X-Model-Harness-Projection':'agent-v1'})
            self.assertEqual(response.status_code,200)
            evidence=response.json()['evidence'];self.assertEqual(base64.b64decode(evidence['content_base64']).decode(),code)
            self.assertEqual(evidence['slice_sha256'],hashlib.sha256(code.encode()).hexdigest())
            self.assertEqual(get.call_args.args,(self.owner,proposal_id))
            foreign=self.client.get(f'/conversations/{self.owner}/context-evidence',params={'kind':'execution_source','object_id':proposal_id,'filename':'/etc/passwd'})
            self.assertEqual(foreign.status_code,404)

    def test_snapshot_reads_never_accept_an_unobserved_foreign_session(self):
        listing=self.client.get(f'/conversations/{self.owner}/context-snapshots')
        self.assertEqual(listing.status_code,200);self.assertEqual(listing.json()['session_id'],self.root)
        response=self.client.get(f'/conversations/{self.owner}/context-snapshots/'+'0'*8+'-'+'0'*4+'-'+'0'*4+'-'+'0'*4+'-'+'0'*12)
        self.assertEqual(response.status_code,404)


if __name__=='__main__':unittest.main()
