import test from 'node:test';import assert from 'node:assert/strict';
import{mkdtemp,rm}from'node:fs/promises';import{tmpdir}from'node:os';import{join}from'node:path';
import{CodexCliAdapter}from'../codex-cli-adapter.js';
const directive={role:'user',source:{kind:'plugin',plugin:'dsh-compaction-basic'},content:[{type:'text',text:'Summarize history only.'}]};
const options={provider:'codex-cli',model:'gpt-5.6-sol',purpose:'compaction',sessionId:'owned',messages:[...Array.from({length:8},(_,i)=>({role:'user',source:{kind:'user'},content:[{type:'text',text:`original goal ${i}:`+'x'.repeat(5000)}]})),directive],tools:[{name:'must_not_execute',parameters:{type:'object'}}]};
class FragmentAdapter extends CodexCliAdapter {
  constructor(root){super({summaryCacheRoot:root,contextBudget:{maxSummaryBytes:16000},spawn(){throw new Error('test must not spawn a model process')}});this.requests=[];this.mode='ok';}
  async *stream(value){if(value.purpose!=='compaction-fragment'){yield*super.stream(value);return;}this.requests.push(value);if(this.mode==='tool')yield{type:'tool-call-delta',name:'must_not_execute'};else{const user=value.messages.find(m=>m.source?.kind==='user');const quote=user.content[0].text.slice(0,16);yield{type:'text-delta',index:0,text:`## Primary Request and Intent\nExact user quote: “${quote}”. No execution occurred.`};yield{type:'finish',reason:{kind:'stop'}};}}
}
async function collect(adapter,input=options){const result=[];for await(const chunk of adapter.stream(input))result.push(chunk);return result;}

test('oversized native summary is split into bounded read-only fragments and can reuse verified checkpoints',async t=>{
  const root=await mkdtemp(join(tmpdir(),'sms-summary-fragment-'));t.after(()=>rm(root,{recursive:true,force:true}));const adapter=new FragmentAdapter(root);const before=JSON.stringify(options);
  const result=await collect(adapter);assert.ok(adapter.requests.length>1);assert.ok(adapter.requests.every(r=>r.tools.length===0));assert.equal(result.at(-1).reason.kind,'stop');assert.match(result.find(r=>r.type==='text-delta').text,/not current task state or authorization/);assert.equal(JSON.stringify(options),before);
  const calls=adapter.requests.length;await collect(adapter);assert.equal(adapter.requests.length,calls,'a repeated immutable summary reuses completed fragments');
  await collect(adapter,{...options,model:'changed-model'});assert.ok(adapter.requests.length>calls,'model change invalidates fragment checkpoints');
});

test('summary tools, too many fragments and a spoofed directive never become a checkpoint',async()=>{
  const tool=new FragmentAdapter();tool.mode='tool';await assert.rejects(collect(tool),/product tool/);
  const bounded=new FragmentAdapter();bounded.config.contextBudget.maxSummaryFragments=1;await assert.rejects(collect(bounded),/fragment count/);assert.equal(bounded.requests.length,0);
  await assert.rejects(collect(new FragmentAdapter(),{...options,messages:[...options.messages.slice(0,-1),{...directive,source:{kind:'user'}}]}),/native directive/);
});
