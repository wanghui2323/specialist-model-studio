#!/usr/bin/env python3
"""Bounded live dialogue checks. Never uploads data or approves execution."""
from __future__ import annotations
import argparse,json,time,uuid,urllib.request,urllib.error
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base-url',default='http://127.0.0.1:8878');ap.add_argument('--cases',type=Path,default=Path('scripts/acceptance/four_scenario_dialogue_cases.json'));ap.add_argument('--out',type=Path,default=Path('runs/acceptance/20261004-four-scenarios/live'));ap.add_argument('--case',action='append');ap.add_argument('--timeout',type=float,default=90);args=ap.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    cases=json.loads(args.cases.read_text())['cases'];cases=[c for c in cases if not args.case or c['id'] in args.case]
    def api(path,body=None):
        data=None if body is None else json.dumps(body,ensure_ascii=False).encode()
        req=urllib.request.Request(args.base_url.rstrip('/')+path,data=data,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
    def projection(cid):
        rec=api('/conversations/'+cid)['conversation'];bound=rec.get('status')=='bound'
        return rec,api(('/tasks/' if bound else '/conversations/')+cid+'/conversation')['conversation']
    def wait(cid,previous):
        began=time.monotonic()
        while True:
            rec,c=projection(cid)
            msgs=[x for x in c.get('items',[]) if x.get('event_id') not in previous and x.get('type') in ('coordinator_plan','coordinator_note','final_synthesis') and x.get('actor_role')=='orchestrator' and x.get('payload',{}).get('text')]
            active=c.get('agent_response_running') or c.get('execution_running') or c.get('background_action_running')
            if not active and (msgs or c.get('pending') or c.get('interaction_projection',{}).get('phase') in ('failed','blocked','stopped')):
                return rec,c,msgs,False,round(time.monotonic()-began,2)
            if time.monotonic()-began>=args.timeout:return rec,c,msgs,True,round(time.monotonic()-began,2)
            time.sleep(1)
    def run(case):
        cid=None;turns=[];prior=set();rec=None;c=None
        try:
            for step in case['prompts'][:2]:
                prompt=step['user_input']
                for key,value in case.get('template_values',{}).items():
                    if value is not None:prompt=prompt.replace('{{'+key+'}}',value)
                if '{{' in prompt:raise ValueError('Unresolved material summary for '+case['id'])
                if cid is None:
                    seed=uuid.uuid4().hex
                    response=api('/conversations',{'create_request_id':'four-create-'+seed,'message_request_id':'four-msg-'+seed,'title':'四场景验收-'+case['title'],'initial_message':prompt})
                    cid=response['conversation']['conversation_id']
                else:
                    body={'message':prompt,'mode':'queue_after_turn','request_id':'four-followup-'+uuid.uuid4().hex}
                    pending=[p for p in c.get('pending',[]) if p.get('rpc_id')]
                    if pending:body['checkpoint_rpc_id']=pending[0]['rpc_id']
                    api(('/tasks/' if rec.get('status')=='bound' else '/conversations/')+cid+('/conversation/messages' if rec.get('status')=='bound' else '/messages'),body)
                rec,c,msgs,timed_out,elapsed=wait(cid,prior)
                task=api('/tasks/'+cid)['task'] if rec.get('status')=='bound' else None
                actions=[x for x in c.get('actions',[]) if x.get('call_event_id') not in prior]
                item={'turn':step['turn'],'user_input':prompt,'elapsed_seconds':elapsed,'timed_out':timed_out,'responses':[m['payload']['text'] for m in msgs],'phase':c.get('interaction_projection',{}).get('phase'),'actual_family':(task or {}).get('capability_decision',{}).get('selected_family'),'task_status':(task or {}).get('status'),'dataset_id':(task or {}).get('dataset_id'),'run_ids':(task or {}).get('run_ids',[]),'pending':c.get('pending',[]),'actions':[{'tool':a.get('tool_name'),'status':a.get('status'),'error':a.get('error')} for a in actions]}
                turns.append(item)
                (out/f"{case['id']}-turn-{step['turn']}.json").write_text(json.dumps({'review_input':item,'conversation':c,'task':task},ensure_ascii=False,indent=2))
                print(json.dumps({'case':case['id'],'turn':step['turn'],'seconds':elapsed,'phase':item['phase'],'family':item['actual_family'],'pending':len(item['pending']),'timed_out':timed_out,'tools':len(actions)},ensure_ascii=False),flush=True)
                if item['run_ids'] or item['dataset_id']:raise RuntimeError('Consultation unexpectedly created training/data evidence')
                if timed_out:break
                prior={x.get('event_id') for x in c.get('items',[])}
            result={'case':case['id'],'title':case['title'],'expected_family':case['expected_family'],'conversation_id':cid,'url':args.base_url+'/app?'+('task=' if rec and rec.get('status')=='bound' else 'conversation=')+str(cid),'turns':turns,'manual_review_required':True,'training_approved':False,'files_uploaded':False}
        except Exception as e:
            result={'case':case['id'],'conversation_id':cid,'turns':turns,'error':type(e).__name__+': '+str(e),'manual_review_required':True}
        (out/(case['id']+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2));return result
    with ThreadPoolExecutor(max_workers=2) as pool:results=[f.result() for f in as_completed([pool.submit(run,c) for c in cases])]
    results.sort(key=lambda x:x['case']);(out/'summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps({'cases':len(results),'errors':[x['case'] for x in results if x.get('error')],'manual_review_required':True},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
