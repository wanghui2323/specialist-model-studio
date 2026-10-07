import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { test } from "node:test";
import { isJsonValue } from "@deepseek-ai/dsh-session";
import { validateJsonSchemaValue } from "@deepseek-ai/dsh-tools";
import { apply } from "../index.js";
import { executionPublicProjection, publicProjection } from "../client.js";
const root = fileURLToPath(new URL("../../../", import.meta.url));
function python(script, input) {
  const result = spawnSync(process.env.PYTHON || "python3", ["-c", script], { cwd: root, input: JSON.stringify(input), encoding: "utf8", maxBuffer: 8 * 1024 * 1024 });
  assert.equal(result.status, 0, result.stderr); return JSON.parse(result.stdout);
}
const buildEnvelope = `
import json,sys,hashlib
from model_harness.isolated_execution import ExecutionBundle
from model_harness.conversation_payloads import engineering_public_projection
value=json.load(sys.stdin)
bundle=ExecutionBundle.from_dict(value['bundle'])
proposal={'object_type':'ExecutionProposal','task_id':'task-protocol-fixture','proposal_id':'execution-'+'e'*24,'base_spec_revision':1,'status':'proposed','execution_spec':{'bundle':bundle.to_dict(),'bundle_sha256':bundle.digest,'capability':{'objective':'unfamiliar_structure_objective'},'config':{'root':0,'cwd':False},'inference':{'schema':value['schema']}},'dataset':{'root':'/Users/private/data'},'logs':{'code':value['bundle']['files']['root'],'argv':['/usr/bin/python','/tmp/private']}}
proposal['proposal_sha256']=hashlib.sha256(json.dumps(proposal,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
body={'proposal':proposal,'execution_spec_schema':value['schema']}
print(json.dumps({'original':body,'projected':engineering_public_projection(body)},ensure_ascii=False))
`;
function fixture() {
  const source = 'cache = "/tmp/model-cache"\npython = "/usr/bin/python"\ninput = "/workspace/input/train/records.csv"\nmarker = "__SMS_VIRTUAL_input__"\nother = "__SMS_SANDBOX_PATH_0__"\n';
  const schema = { type: "object", required: ["root", "source_path", "cwd"], properties: { root: { type: "number" }, source_path: { type: "string" }, cwd: { type: "boolean" } } };
  const bundle = { files: { root: source, source_path: "print(1)\n" }, stages: { qualify: ["/usr/bin/python", "/workspace/source/root", "--cache", "/tmp/model-cache"] }, image: `python@sha256:${"a".repeat(64)}`, limits: { cpus: 1.5, timeout_seconds: 7.5 } };
  return { source, schema, bundle };
}

test("Python engineering projection → actual JS tool producer → DSH schema → Python ObjectRef descriptor → exact UI reader", async () => {
  const input = fixture(), envelopes = python(buildEnvelope, input), registered = [];
  apply({ tools: { register: tool => registered.push(tool) }, systemPrompt: { section() {} }, on() {} });
  const tool = registered.find(item => item.name === "model_harness_get_execution_proposal"), originalFetch = globalThis.fetch;
  const args = { task_id: envelopes.original.proposal.task_id, proposal_id: envelopes.original.proposal.proposal_id };
  assert.deepEqual(validateJsonSchemaValue(tool.parameters, args), []);
  globalThis.fetch = async (_url, options) => {
    assert.equal(options.headers["X-Model-Harness-Projection"], "agent-execution-v1");
    return new Response(JSON.stringify(envelopes.projected), { headers: { "content-type": "application/json" } });
  };
  try {
    const result = await tool.execute(args, {});
    assert.equal(isJsonValue(result), true); assert.deepEqual(validateJsonSchemaValue(tool.output.schema, result), []);
    assert.deepEqual(result.execution_spec_schema, input.schema); assert.equal(result.proposal.execution_spec.bundle.files.root, input.source);
    assert.deepEqual(result.proposal.execution_spec.bundle.stages.qualify, input.bundle.stages.qualify);
    assert.equal(result.proposal.execution_spec.config.root, 0); assert.equal(result.proposal.execution_spec.config.cwd, false);
    assert.equal(result.proposal.dataset.root, undefined); assert.doesNotMatch(result.proposal.logs.code, /\/tmp\/|\/usr\//);
    const contract = python(`
import json,sys
from model_harness.object_refs import normalize_object_refs, exact_object_ref_endpoint, OBJECT_REF_DESCRIPTORS
from model_harness.isolated_execution import ExecutionBundle
value=json.load(sys.stdin)
refs=normalize_object_refs(value['object_refs'],expected_task_id=value['proposal']['task_id'],require_nonempty=True)
assert len(refs)==1 and refs[0].type=='execution_proposal'
assert ExecutionBundle.from_dict(value['proposal']['execution_spec']['bundle']).digest==value['proposal']['execution_spec']['bundle_sha256']
print(json.dumps({'ref':refs[0].as_dict(),'endpoint':exact_object_ref_endpoint(refs[0]),'selector':OBJECT_REF_DESCRIPTORS[refs[0].type].response_selector}))
`, result);
    assert.equal(contract.selector, "proposal"); assert.equal(contract.ref.digest, result.proposal.proposal_sha256);
    const app = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
    const section = (from, to) => app.slice(app.indexOf(from), app.indexOf(to, app.indexOf(from) + from.length));
    const context = { state: { selectedTaskId: args.task_id }, TERMINAL_RESULT_REF_TYPES: new Set() };
    vm.runInNewContext(section("function normalizeObjectRefType", "function objectViewerPresentation") + section("function returnedObjectMatchesRef", "async function openObjectRef") + "\nglobalThis.endpoint=objectRefEndpoint;globalThis.matches=returnedObjectMatchesRef;", context);
    assert.equal(context.endpoint(contract.ref), contract.endpoint); assert.equal(context.matches(contract.ref, result), true);
    assert.equal(context.matches(contract.ref, { proposal: { ...result.proposal, task_id: "foreign" } }), false);
    assert.equal(context.matches(contract.ref, { proposal: { ...result.proposal, proposal_sha256: "0".repeat(64) } }), false);
  } finally { globalThis.fetch = originalFetch; }
});

test("unbound source-like logs and ordinary projections keep host redaction while literal markers remain literal", () => {
  const input = fixture();
  const value = { execution_spec: { bundle: input.bundle, config: { root: 0, source_path: "/Users/private/file" }, inference: { schema: input.schema } }, logs: { files: input.bundle.files, code: input.source }, marker: "__SMS_VIRTUAL_input__" };
  const engineering = executionPublicProjection(value);
  assert.deepEqual(engineering.execution_spec.inference.schema, input.schema); assert.equal(engineering.execution_spec.config.root, 0); assert.equal(engineering.execution_spec.config.source_path, undefined);
  assert.doesNotMatch(engineering.execution_spec.bundle.files.root, /\/tmp\/|\/usr\//); assert.doesNotMatch(engineering.logs.code, /\/tmp\/|\/usr\//);
  assert.equal(engineering.marker, value.marker); assert.doesNotMatch(JSON.stringify(publicProjection(value)), /\/workspace\/input/);
});


test("bare immutable image IDs preserve the frozen source and argv bytes across both projection layers", () => {
  const input = fixture(); input.bundle.image = `sha256:${"a".repeat(64)}`;
  const envelopes = python(buildEnvelope, input), output = executionPublicProjection(envelopes.projected);
  assert.equal(output.proposal.execution_spec.bundle.image, input.bundle.image);
  assert.equal(output.proposal.execution_spec.bundle.files.root, input.source);
  assert.deepEqual(output.proposal.execution_spec.bundle.stages.qualify, input.bundle.stages.qualify);
  const digest = python("import json,sys;from model_harness.isolated_execution import ExecutionBundle; print(json.dumps(ExecutionBundle.from_dict(json.load(sys.stdin)).digest))", output.proposal.execution_spec.bundle);
  assert.equal(digest, envelopes.original.proposal.execution_spec.bundle_sha256);
});

test("workspace protocol cwd survives Python and JS engineering projection without broadening host or log access", () => {
  const payload = { execution_workspace: { protocol: { working_directory: "/workspace/output" }, execution_spec_schema: { "x-protocol": { working_directory: "/workspace/output" } } }, working_directory: "/workspace/output", logs: { protocol: { working_directory: "/workspace/output" } } };
  const projected = python("import json,sys;from model_harness.conversation_payloads import engineering_public_projection;print(json.dumps(engineering_public_projection(json.load(sys.stdin))))", payload);
  const result = executionPublicProjection(projected);
  assert.equal(result.execution_workspace.protocol.working_directory, "/workspace/output");
  assert.equal(result.execution_workspace.execution_spec_schema["x-protocol"].working_directory, "/workspace/output");
  assert.equal(result.working_directory, undefined); assert.equal(result.logs.protocol.working_directory, undefined);
  assert.equal(publicProjection(payload).execution_workspace.protocol.working_directory, undefined);
  for (const unsafe of ["/Users/private/cache", "/tmp/host-cache", "/workspace/output/../private", "/workspace/output\\private", "/workspace/output\nprivate"]) {
    payload.execution_workspace.protocol.working_directory = unsafe;
    assert.equal(executionPublicProjection(payload).execution_workspace.protocol.working_directory, undefined);
  }
});
