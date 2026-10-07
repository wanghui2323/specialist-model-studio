import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,writeFile,rm,mkdir,symlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {PageAcceptanceDriver} from '../../../scripts/acceptance/cua-page-driver.mjs';

async function fixture(t, options={}) {
  const root=await mkdtemp(join(tmpdir(),'sms-page-driver-'));
  t.after(()=>rm(root,{recursive:true,force:true}));
  const calls=[];
  const tab={url:async()=>'http://localhost/app?task=owned',screenshot:async()=>Buffer.from('unit-test-screenshot'),
    playwright:{domSnapshot:async()=>'- main:\n  - button "开始训练"\n  - textbox "向 Specialist Model Studio 描述模型任务"',
      getByRole:(_role,{name})=>({fill:async text=>calls.push(['fill',text]),isEnabled:async()=>true,click:async()=>calls.push(['click',name])}),
      waitForEvent:async()=>({setFiles:async files=>calls.push(['files',files])})},
    reload:async()=>calls.push(['reload'])};
  return {root,calls,tab,driver:new PageAcceptanceDriver({tab,caseId:'arbitrary-objective',evidenceDir:root,...options})};
}

test('real driver binds captured bytes and UI action without a product API or browser launcher',async t=>{
  const f=await fixture(t);const row=await f.driver.send('普通用户目标');
  assert.deepEqual(f.calls,[['fill','普通用户目标'],['click','发送消息']]);
  const journal=JSON.parse((await readFile(join(f.root,'journal.jsonl'),'utf8')).trim());
  assert.equal(journal.id,row.id);assert.equal(journal.case_id,'arbitrary-objective');
  assert.equal(journal.snapshot.sha256.length,64);assert.equal(journal.screenshot.sha256.length,64);
});

test('ordinary exploration cannot click an arbitrary approval or approve without a grant',async t=>{
  const f=await fixture(t);
  await assert.rejects(f.driver.click('开始训练'),/reviewed page action/);
  await assert.rejects(f.driver.approve('开始训练','invented'),/one-shot grant/);
  assert.deepEqual(f.calls,[]);
});

test('approval requires exact observed bytes and is consumed once',async t=>{
  const f=await fixture(t);const row=await f.driver.capture();
  const approved=new PageAcceptanceDriver({tab:f.tab,caseId:'arbitrary-objective',evidenceDir:f.root,approvals:[{label:'开始训练',observation_id:row.id,snapshot_sha256:row.snapshot.sha256,scope:{task_id:'owned',run_budget:'test-only'}}]});
  await approved.approve('开始训练',row.id);
  assert.equal(f.calls.filter(c=>c[0]==='click').length,1);
  await assert.rejects(approved.approve('开始训练',row.id),/one-shot grant/);
});

test('stale page cannot consume a reviewed approval',async t=>{
  const f=await fixture(t);const row=await f.driver.capture();
  const approved=new PageAcceptanceDriver({tab:f.tab,caseId:'arbitrary-objective',evidenceDir:f.root,approvals:[{label:'开始训练',observation_id:row.id,snapshot_sha256:row.snapshot.sha256,scope:{task_id:'owned'}}]});
  f.tab.playwright.domSnapshot=async()=>'- main: changed task or scope';
  await assert.rejects(approved.approve('开始训练',row.id),/page changed/);
  assert.deepEqual(f.calls,[]);
});

test('ungranted and symlink-escaped fixture files never reach the chooser',async t=>{
  const f=await fixture(t);const fixtures=join(f.root,'fixtures');await mkdir(fixtures);
  const file=join(fixtures,'allowed.csv');await writeFile(file,'x,y\n1,2\n');
  const foreign=join(f.root,'reviewer-answers.json');await writeFile(foreign,'private judge expectations');
  const link=join(fixtures,'escape.csv');await symlink(foreign,link);
  const driver=new PageAcceptanceDriver({tab:f.tab,caseId:'arbitrary-objective',evidenceDir:f.root,fixtureRoot:fixtures,permittedFiles:[file,link]});
  await assert.rejects(driver.upload('上传材料',[foreign]),/upload grant/);
  await assert.rejects(driver.upload('上传材料',[link]),/symlink/);
  assert.deepEqual(f.calls,[]);
  await driver.upload('上传材料',[file]);
  assert.deepEqual(f.calls,[['click','上传材料'],['files',[file]]]);
});

test('bounded actions stop exploration rather than silently looping',async t=>{
  const f=await fixture(t,{maxActions:1});await f.driver.reload();
  await assert.rejects(f.driver.reload(),/budget exhausted/);
  assert.throws(()=>new PageAcceptanceDriver({tab:f.tab,caseId:'x',evidenceDir:f.root,maxActions:Infinity}),/finite positive/);
});
