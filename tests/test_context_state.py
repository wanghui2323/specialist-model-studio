import json
import tempfile
import unittest
from pathlib import Path
from model_harness.context_state import ContextStateError, ContextStateStore


class ContextStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=ContextStateStore(Path(self.tmp.name)); self.owner='模型-目标-1'
        self.provenance={'session_id':'root-owned','call_id':'call-1'}
        self.message='我已经决定从零训练，用自己的声音读新的文字。CPU最多2核，内存4GiB。'
        self.runs=[{'run_id':'agent-run-1','user_message':self.message,'composer_request':{'request_id':'request-1','actor':'user'}}]
        self.state=self.store.ingest_prompt_runs(self.owner,self.runs)

    def entry(self, **changes):
        return {'slot':'training_route','kind':'user_explicit','value':'from_scratch','source_request_id':'request-1','quote':'决定从零训练',**changes}

    def record(self, entries=None, **changes):
        return self.store.record(self.owner,base_revision=changes.pop('base_revision',self.state['revision']),update_id=changes.pop('update_id','update-1'),entries=entries or [self.entry()],provenance=changes.pop('provenance',self.provenance),**changes)

    def test_quote_linked_goal_survives_restart_without_becoming_authorization(self):
        self.record(); resumed=ContextStateStore(Path(self.tmp.name)).snapshot(self.owner)
        self.assertEqual(resumed['entries'][0]['value'],'from_scratch')
        self.assertEqual(resumed['entries'][0]['quote'],'决定从零训练')
        self.assertEqual(resumed['entries'][0]['interpretation_status'],'agent_derived_quote_verified_only')
        self.assertFalse(resumed['entries'][0]['grants_execution_authorization'])
        self.assertFalse(resumed['grants_execution_authorization'])

    def test_replayed_message_and_same_update_with_new_call_do_not_duplicate_decisions(self):
        self.assertEqual(self.store.ingest_prompt_runs(self.owner,self.runs),self.state)
        first=self.record()
        replay=self.record(provenance={**self.provenance,'call_id':'call-retry'})
        self.assertEqual(first,replay)
        self.assertEqual(len(replay['entries']),1)

    def test_mutated_message_and_reused_update_are_rejected(self):
        with self.assertRaises(ContextStateError): self.store.ingest_prompt_runs(self.owner,[{**self.runs[0],'user_message':'changed'}])
        self.record()
        with self.assertRaises(ContextStateError): self.record(entries=[self.entry(value='fine_tuning')])

    def test_old_choice_is_superseded_and_immutable_revision_is_preserved(self):
        first=self.record(); path=self.store.directory(self.owner)/'revisions'/f"{first['revision']:08d}.json"; before=path.read_bytes()
        second=self.record(entries=[self.entry(value='random_initialization_small_model')],base_revision=first['revision'],update_id='update-2')
        self.assertEqual(second['entries'][0]['status'],'superseded')
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(self.store.snapshot(self.owner)['entries'][0]['value'],'random_initialization_small_model')

    def test_foreign_or_fabricated_quotes_and_host_control_slots_fail(self):
        for entry in [self.entry(source_request_id='foreign'),self.entry(quote='从未说过'),self.entry(slot='authorization.allow'),{**self.entry(),'approval':True}]:
            with self.assertRaises(ContextStateError): self.record(entries=[entry])
        self.assertEqual(self.store.read(self.owner)['revision'],self.state['revision'])

    def test_system_notice_cannot_become_user_confirmation(self):
        self.state=self.store.ingest_prompt_runs(self.owner,[{'run_id':'system','user_message':'同意训练','composer_request':{'request_id':'system-request','actor':'system'}}])
        with self.assertRaises(ContextStateError): self.record(entries=[self.entry(source_request_id='system-request',quote='同意训练')])

    def test_stale_revision_and_oversized_state_cannot_silently_replace_current_memory(self):
        self.record()
        with self.assertRaises(ContextStateError): self.record(update_id='new-with-stale-revision')
        active=self.store.read(self.owner)
        entries=[self.entry(slot=f'constraints.item{i}',value='很长的约束'*300) for i in range(8)]
        with self.assertRaises(ContextStateError): self.record(entries=entries,base_revision=active['revision'],update_id='too-large')
        self.assertEqual(self.store.read(self.owner),active)

    def test_range_reader_reports_completeness_and_reassembles_exact_user_text(self):
        first=self.store.message(self.owner,'request-1',max_chars=7)
        self.assertFalse(first['complete']);self.assertTrue(first['has_more'])
        second=self.store.message(self.owner,'request-1',start=7,max_chars=1000)
        self.assertEqual(first['text']+second['text'],self.message)
        self.assertEqual(first['text_sha256'],second['text_sha256'])
        with self.assertRaises(FileNotFoundError): self.store.message('foreign-owner','request-1')

    def test_corruption_and_path_escape_are_distinct_from_empty_memory(self):
        p=self.store.directory(self.owner)/'state.json'; data=json.loads(p.read_text());data['owner_id']='foreign';p.write_text(json.dumps(data))
        with self.assertRaises(ContextStateError): self.store.snapshot(self.owner)
        for owner in ('../foreign','a/b','a\\b','..'):
            with self.assertRaises(ContextStateError): self.store.snapshot(owner)

    def test_unseen_business_slots_are_open_and_semantics_are_not_machine_confirmation(self):
        value=self.record(entries=[self.entry(slot='inputs.future_sensor',value='arbitrary waveform and trajectory')])
        self.assertEqual(value['entries'][0]['slot'],'inputs.future_sensor')
        self.assertEqual(value['entries'][0]['interpretation_status'],'agent_derived_quote_verified_only')


if __name__=='__main__':unittest.main()
