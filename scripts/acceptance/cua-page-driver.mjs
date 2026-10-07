// Import this module inside cua_repl, then pass its already selected tab.
// This module does not open a browser, use CDP, fetch product APIs or bypass UI.
import { appendFile, mkdir, writeFile, readFile, realpath } from 'node:fs/promises';
import { resolve, relative, isAbsolute, sep } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
export class PageAcceptanceDriver {
  constructor({tab, caseId, evidenceDir, fixtureRoot, permittedFiles = [], maxActions = 40, maxSeconds = 180, approvals = []}) {
    if (!tab || !caseId || !evidenceDir) throw new Error('selected CUA tab and case evidence directory required');
    this.tab = tab; this.caseId = caseId; this.dir = resolve(evidenceDir);
    this.fixtureRoot = fixtureRoot && resolve(fixtureRoot);
    this.permittedFiles = new Set(permittedFiles.map(path => resolve(path)));
    if (!Number.isInteger(maxActions) || maxActions < 1 || maxActions > 1000 || !Number.isFinite(maxSeconds) || maxSeconds < 1) throw new Error('finite positive action/time budget required');
    this.deadline = Date.now() + maxSeconds * 1000;
    this.remaining = maxActions; this.approvals = new Map(approvals.map(row => [row.label, structuredClone(row)]));
  }
  async capture(action = {kind:'observe'}, actionStatus = 'completed', error = null) {
    await mkdir(this.dir, {recursive:true});
    const id = randomUUID(), snapshot = await this.tab.playwright.domSnapshot();
    const screenshot = await this.tab.screenshot({fullPage:false});
    const snapName = `${id}.txt`, imageName = `${id}.png`;
    await writeFile(resolve(this.dir, snapName), snapshot, {flag:'wx'});
    await writeFile(resolve(this.dir, imageName), screenshot, {flag:'wx'});
    const row = {id, case_id:this.caseId, observed_at:new Date().toISOString(), url:await this.tab.url(), action, action_status:actionStatus,
      snapshot:{path:snapName, sha256:hash(snapshot)}, screenshot:{path:imageName, sha256:hash(screenshot)}};
    if (error) row.error = error; // callers must pass non-secret diagnostics
    await appendFile(resolve(this.dir, 'journal.jsonl'), JSON.stringify(row) + '\n');
    return {...row, text:snapshot};
  }
  budget() { if (Date.now() > this.deadline || this.remaining-- <= 0) throw new Error('page action/time budget exhausted; record incomplete rather than loop'); }
  async send(text) {
    this.budget();
    const input = this.tab.playwright.getByRole('textbox',{name:'向 Specialist Model Studio 描述模型任务',exact:true});
    const button = this.tab.playwright.getByRole('button',{name:'发送消息',exact:true});
    await input.fill(text);
    if (!await button.isEnabled()) throw new Error('composer unavailable; inspect current page before sending');
    await button.click();
    return this.capture({kind:'send',text});
  }
  async click(label) {
    this.budget();
    // All arbitrary clicks could conceal approval (including new copy).
    // No blind generic click API: use the dedicated non-privileged methods,
    // or approve after an exact observation-scoped grant.
    throw new Error(`Use a reviewed page action method for ${label}`);
  }
  async startConversation() {
    this.budget();
    const menu=this.tab.playwright.getByRole('button',{name:'打开任务列表',exact:true});
    if(await menu.count() && await menu.isVisible())await menu.click();
    await this.tab.playwright.getByRole('button',{name:'开始新任务',exact:true}).click();
    await this.tab.playwright.getByRole('heading',{name:'你想让模型解决什么问题？',exact:true}).waitFor({state:'visible',timeoutMs:10000});
    return this.capture({kind:'start_conversation',label:'开始新任务'});
  }
  async selectTask(label) {
    this.budget();
    const menu=this.tab.playwright.getByRole('button',{name:'打开任务列表',exact:true});
    if(await menu.count() && await menu.isVisible())await menu.click();
    await this.tab.playwright.getByRole('navigation',{name:'任务列表',exact:true}).getByRole('button',{name:label,exact:true}).click();
    return this.capture({kind:'select_task',label});
  }
  async upload(label, files) {
    this.budget();
    if (!this.fixtureRoot || !files.length) throw new Error('declared synthetic/public fixture files required');
    const realRoot = await realpath(this.fixtureRoot);
    for (const file of files) {
      const path = resolve(file), rel = relative(this.fixtureRoot, path);
      if (!rel || rel === '..' || rel.startsWith('..' + sep) || isAbsolute(rel) || !this.permittedFiles.has(path)) throw new Error('file outside the exact fixture upload grant');
      const realRel = relative(realRoot, await realpath(path));
      if (!realRel || realRel === '..' || realRel.startsWith('..'+sep) || isAbsolute(realRel)) throw new Error('fixture symlink escapes upload grant');
      // Expected outcomes, private judges and held-out new-sample answers
      // must never be among permittedFiles. Only the reviewed case manifest
      // can grant real training split archives to the product.
    }
    const button = this.tab.playwright.getByRole('button',{name:label,exact:true});
    if (!await button.isEnabled()) throw new Error('upload unavailable; record the real blocker without forcing it');
    const waiting = this.tab.playwright.waitForEvent('filechooser',{timeoutMs:10000});
    try { await button.click(); await (await waiting).setFiles(files); }
    catch (error) { waiting.catch(()=>{}); throw error; }
    const manifests = await Promise.all(files.map(async path => ({filename:relative(this.fixtureRoot,resolve(path)),sha256:hash(await readFile(path))})));
    return this.capture({kind:'upload',label,files:manifests});
  }
  async approve(label, observationId) {
    this.budget();
    const grant = this.approvals.get(label);
    if (!grant || grant.observation_id !== observationId || !grant.scope || !grant.snapshot_sha256) throw new Error('approval requires one reviewed exact capture, explicit scope and one-shot grant');
    const rows = (await readFile(resolve(this.dir,'journal.jsonl'),'utf8')).trim().split('\n').map(JSON.parse);
    const row = rows.find(value => value.id === observationId);
    if (!row || row.case_id !== this.caseId || row.snapshot.sha256 !== grant.snapshot_sha256) throw new Error('approval observation mismatch');
    const now = await this.tab.playwright.domSnapshot();
    if (hash(now) !== grant.snapshot_sha256) throw new Error('page changed since approval review; observe and review scope again');
    const button = this.tab.playwright.getByRole('button',{name:label,exact:true});
    if (!await button.isEnabled()) throw new Error('approval unavailable');
    this.approvals.delete(label); await button.click();
    return this.capture({kind:'approve',label,scope:grant.scope,reviewed_observation_id:observationId});
  }
  async reload() { this.budget(); await this.tab.reload(); return this.capture({kind:'reload'}); }
}
