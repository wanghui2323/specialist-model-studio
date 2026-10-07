import test from 'node:test';import assert from 'node:assert/strict';
import{mkdtemp,readFile,rm,stat,writeFile}from'node:fs/promises';import{join}from'node:path';import{tmpdir}from'node:os';
import{persistContextSnapshot,snapshotHash,contextDiff}from'../context-snapshot.js';
import{contextBudget,budgetAssessment,balancedMessageGroups,splitContextMessages,verifiedSummaryQuotes}from'../context-budget.js';

test('private wire snapshots preserve actual input and immutable parent/diff evidence',async t=>{
  const root=await mkdtemp(join(tmpdir(),'sms-context-snapshot-'));t.after(()=>rm(root,{recursive:true,force:true}));
  const trace={session_id:'root-owned',provider:'any-provider',model:'selected',purpose:'agent',policy_revision:'test'};
  const a={baseInstructions:'stable rules',tools:[{name:'read'}],history:[{role:'user',content:'明确目标'}],continuation:'continue'};
  const first=await persistContextSnapshot(root,trace,a);const file=join(root,'_workspace/context-snapshots/root-owned',first.snapshot_id+'.json');const before=await readFile(file,'utf8');
  assert.equal(JSON.parse(before).wire_context_sha256,snapshotHash(a));assert.equal((await stat(file)).mode&0o777,0o600);
  const second=await persistContextSnapshot(root,trace,{...a,history:[...a.history,{role:'user',content:'新的约束'}]});
  assert.equal(second.parent_snapshot_id,first.snapshot_id);assert.equal(second.diff.added.length,1);assert.equal(second.diff.removed.length,0);
  assert.equal(await readFile(file,'utf8'),before);assert.equal(JSON.parse(before).grants_execution_authorization,false);
  await assert.rejects(persistContextSnapshot(root,{...trace,session_id:'../foreign'},a),/identity/);
});

test('snapshot corruption does not silently become a fresh empty history',async t=>{
  const root=await mkdtemp(join(tmpdir(),'sms-context-corrupt-'));t.after(()=>rm(root,{recursive:true,force:true}));const trace={session_id:'owned'};
  const first=await persistContextSnapshot(root,trace,{history:[],tools:[]});const p=join(root,'_workspace/context-snapshots/owned',first.snapshot_id+'.json');await writeFile(p,'{"session_id":"foreign"}');
  await assert.rejects(persistContextSnapshot(root,trace,{history:[],tools:[]}),/digest/);
});

test('context diff counts duplicate evidence and records stable rule/tool changes',()=>{
  const same={role:'user',content:'same'};const d=contextDiff({history:[same,same],baseInstructions:'old',tools:[]},{history:[same],baseInstructions:'new',tools:[{name:'read'}]});
  assert.equal(d.removed[0].count,1);assert.equal(d.system_changed,true);assert.equal(d.tools_changed,true);
});

test('summary budget is independent, finite and explicitly estimates rather than claims exact tokens',()=>{
  const b=contextBudget();assert.ok(b.max_summary_bytes<b.max_input_bytes);assert.equal(budgetAssessment(400000,'compaction',b).action,'split_or_reject');
  assert.equal(budgetAssessment(400000,'agent',b).action,'within_budget');assert.match(b.token_estimate_source,/not_exact/);
  for(const config of [{maxInputBytes:Infinity},{maxSummaryBytes:800000},{maxSummaryFragments:NaN},{maxSummaryFragments:0}])assert.throws(()=>contextBudget(config));
});

test('fragment boundaries preserve parallel tool pairs, user decisions and exact source content',()=>{
  const user={role:'user',content:[{type:'text',text:'从零训练，预算不能增加。'+'x'.repeat(2000)}]};
  const call={role:'assistant',content:[{type:'tool-call',id:'a',name:'read',arguments:'{}'},{type:'tool-call',id:'b',name:'read',arguments:'{}'}]};
  const output=id=>({role:'user',content:[{type:'tool-result',toolCallId:id,content:[{type:'text',text:'data'}]}]});
  const messages=[user,call,output('b'),output('a'),user,user];const before=JSON.stringify(messages);const groups=balancedMessageGroups(messages);
  assert.equal(groups[1].length,3);const chunks=splitContextMessages(messages,4500,500);assert.ok(chunks.length>1);
  assert.deepEqual(chunks.flat(),messages);assert.equal(JSON.stringify(messages),before);
  for(const chunk of chunks)assert.doesNotThrow(()=>balancedMessageGroups(chunk));
  assert.throws(()=>balancedMessageGroups([output('foreign')]),/without/);assert.throws(()=>balancedMessageGroups([call]),/incomplete/);
  assert.throws(()=>splitContextMessages([{role:'user',content:[{type:'text',text:'x'.repeat(9000)}]}],4500,500),/exceeds/);
});

test('working checkpoints retain exact source quotes but exclude invented history and host directives',()=>{
  const messages=[{role:'user',source:{kind:'user'},content:[{type:'text',text:'Only daily totals, not per item. Do not train.'}]},{role:'system',source:{kind:'plugin',plugin:'dsh-compaction-basic'},content:[{type:'text',text:'Summarize this archive'}]}];
  const quotes=verifiedSummaryQuotes('Latest user goal: “Summarize this archive”. Prior choice: “per-item forecasts selected”. Actual choice: “Only daily totals, not per item.” Constraint: “Do not train.”',messages);
  assert.deepEqual(quotes.map(q=>q.quote),['Only daily totals, not per item.','Do not train.']);assert.ok(quotes.every(q=>q.source_kind==='user'));
});
