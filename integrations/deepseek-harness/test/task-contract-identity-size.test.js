import test from "node:test";
import assert from "node:assert/strict";
import { compactTaskForAgent, ModelHarnessClient } from "../client.js";

const sha = "a".repeat(64);
function largeTask() {
  const spec = { bundle_sha256: "b".repeat(64), bundle: { files: { "run.py": "source\n".repeat(30000) }, image: "sha256:" + sha, stages: { train: ["python", "/workspace/source/run.py"] }, limits: { timeout_seconds: 180 } }, inference: { extensions: [".json"], max_bytes: 1000 }, evaluation: { gates: { quality: { operator: "gte", threshold: 0.8 } } } };
  const contract = { business_goal: "original goal", execution_spec: spec };
  return { task: { task_id: "task-owned", contract, contract_revision: { contract_revision_id: "revision-owned", contract_sha256: sha, task_id: "task-owned", spec_revision_id: "task-owned:spec:r1", dataset_id: "dataset-owned", dataset_fingerprint_sha256: "c".repeat(64), contract_snapshot: structuredClone(contract), revision_sha256: "d".repeat(64) }, current_spec_revision: 1, current_contract_revision_id: "revision-owned", dataset_id: "dataset-owned", confirmed_contract_sha256: null, task_spec: { revision_id: "task-owned:spec:r1" }, dataset_report: { fingerprint_sha256: "c".repeat(64) } } };
}

test("large generic source snapshots cannot push current contract identity into omitted tool output", () => {
  const raw = largeTask(), before = JSON.stringify(raw), projected = compactTaskForAgent(raw), formatted = JSON.stringify(projected, null, 2);
  assert.ok(before.length > 400000); assert.ok(formatted.length < 10000);
  for (const field of ["contract_revision_id", "contract_sha256", "task_id", "spec_revision_id", "dataset_id", "dataset_fingerprint_sha256"]) assert.equal(projected.task.contract_revision[field], raw.task.contract_revision[field]);
  assert.ok(formatted.indexOf('"contract_sha256"') < 500);
  assert.equal(projected.task.contract_revision.revision_sha256, "d".repeat(64));
  assert.equal(projected.task.contract.business_goal, "original goal"); assert.deepEqual(projected.task.contract.execution_spec.inference, raw.task.contract.execution_spec.inference); assert.deepEqual(projected.task.contract.execution_spec.evaluation, raw.task.contract.execution_spec.evaluation);
  assert.deepEqual(projected.task.contract.execution_spec.bundle.source_file_names, ["run.py"]); assert.equal(projected.task.contract.execution_spec.bundle.files, undefined); assert.equal(JSON.stringify(raw), before);
});

test("HTTP task read retains exact confirmation identity; legacy task stays unchanged", async () => {
  const client = new ModelHarnessClient(), original = globalThis.fetch, raw = largeTask();
  globalThis.fetch = async () => new Response(JSON.stringify(raw), { headers: { "Content-Type": "application/json" } });
  try { const task = (await client.getTask("task-owned")).task; assert.equal(task.contract_revision.contract_sha256, sha); assert.equal(task.current_contract_revision_id, task.contract_revision.contract_revision_id); assert.equal(task.task_spec.revision_id, task.contract_revision.spec_revision_id); assert.equal(task.dataset_report.fingerprint_sha256, task.contract_revision.dataset_fingerprint_sha256); } finally { globalThis.fetch = original; }
  const legacy = { task: { task_id: "legacy", contract: { recipe: "builtin", business_goal: "unchanged" } } }; assert.deepEqual(compactTaskForAgent(legacy), legacy);
});

test("all report envelopes compact repeated generic task evidence without changing canonical result or approvals", async () => {
  const raw=largeTask(); raw.task.contract.dataset={dataset_id:'dataset-owned',fingerprint_sha256:sha,files:Array.from({length:300},(_,i)=>({path:`train/${i}.wav`,sha256:sha})),split_manifest:{train:['owned'],test:['held-out']},splits:{train:[{path:'train/one.wav'}],test:[{path:'test/one.wav'}]}};
  raw.task.current_result={status:'completed',quality_gates_passed:false,dataset:structuredClone(raw.task.contract.dataset)};
  raw.evaluation_report={report_id:'report-owned',report_sha256:sha,quality:{passed:false},metrics:{cer:.8}};
  const before=JSON.stringify(raw),original=globalThis.fetch,client=new ModelHarnessClient();
  globalThis.fetch=async()=>new Response(JSON.stringify(raw),{headers:{'Content-Type':'application/json'}});
  try {
    const projected=await client.request('/tasks/task-owned/runs/run-owned/evaluation-report');
    assert.deepEqual(projected.evaluation_report,raw.evaluation_report);
    assert.equal(projected.task.contract_revision.contract_sha256,sha);
    assert.equal(projected.task.contract_revision.contract_snapshot,undefined);
    assert.equal(projected.task.contract.dataset.files,undefined);
    assert.equal(projected.task.contract.dataset.files_reference.entries,300);
    assert.equal(projected.task.contract.dataset.splits,undefined);
    assert.deepEqual(projected.task.contract.dataset.split_file_counts,{train:1,test:1});
    assert.equal(projected.task.current_result.quality_gates_passed,false);
    assert.ok(JSON.stringify(projected).length<10000);
    assert.equal(JSON.stringify(raw),before);
  } finally {globalThis.fetch=original;}
});
