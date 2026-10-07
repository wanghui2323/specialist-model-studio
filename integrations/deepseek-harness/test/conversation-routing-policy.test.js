import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { apply, SOLUTION_CONSULTATION_GUIDANCE as REEXPORTED_GUIDANCE } from "../index.js";
import { SOLUTION_CONSULTATION_GUIDANCE as policy } from "../consultation-policy.js";

function mountRoutingPlugin() {
  const tools = [], sections = [], listeners = new Map();
  apply({ tools: { register: tool => tools.push(tool) }, systemPrompt: { section: value => sections.push(value) }, on: (event, handler) => listeners.set(event, handler) });
  return { tools, sections, listeners };
}
function mountedRoutingPrompt() {
  return mountRoutingPlugin().sections.find(section => section.name === "domain:model-training-harness")?.text || "";
}

test("promotion accepts unfamiliar capabilities and historical objective aliases without rewriting their meaning", async () => {
  const tool = mountRoutingPlugin().tools.find(tool => tool.name === "model_harness_promote_conversation");
  for (const field of ["modality", "objective", "target_kind", "input_description", "output_description", "training_route"]) {
    assert.equal(tool.parameters.properties.capability_request.properties[field].type, "string");
    assert.equal(tool.parameters.properties.capability_request.properties[field].enum, undefined);
  }
  const originalFetch = globalThis.fetch, requests = [];
  globalThis.fetch = async (_url, options) => {
    const body = JSON.parse(options.body); requests.push(body);
    return new Response(JSON.stringify({ promoted: true, task: { task_id: "open-goal", recipe_id: null, current_run_id: null, blockers: [] },
      conversation: { conversation_id: "open-goal", task_id: "open-goal", status: "bound" } }), { headers: { "content-type": "application/json" } });
  };
  try {
    for (const capability of [
      { modality: "molecular_graph", objective: "conditional_structure_generation", target_kind: "variable_size_graph", constraint: "preserve_atom_types", input_description: "一个可变大小的分子图", output_description: "满足约束的新分子结构", training_route: "from_scratch" },
      { modality: "audio", objective: "speech_to_text", target_kind: "transcript" },
    ]) {
      const result = await tool.execute({ conversation_id: "open-goal", name: "具体目标", business_goal: "保留用户的目标，准备并验证训练实现", capability_request: capability }, { callId: `promote-${requests.length}` });
      assert.deepEqual(requests.at(-1).capability_request, capability);
      assert.equal("recipe_id" in requests.at(-1), false);
      assert.equal(result.task.recipe_id, null);
      assert.equal(result.task.current_run_id, null);
    }
  } finally { globalThis.fetch = originalFetch; }
});

test("an unfamiliar output family and explicit training route survive the real spec-update tool unchanged", async () => {
  const tool = mountRoutingPlugin().tools.find(tool => tool.name === "model_harness_update_task_spec");
  const originalFetch = globalThis.fetch, requests = [];
  globalThis.fetch = async (_url, options) => {
    const body = JSON.parse(options.body); requests.push(body);
    return new Response(JSON.stringify({ task: { task_id: "task-open-route", current_spec_revision: body.base_revision + 1, recipe_id: null, current_run_id: null, blockers: [] } }), { headers: { "content-type": "application/json" } });
  };
  try {
    for (const [routeId, route] of [["from_scratch", "用户明确要求从随机初始化训练一个小模型，不使用预训练权重"], ["finetune", "用户明确要求在已有权重上微调，保留该路线"], ["curriculum_distillation", "用户选择课程式蒸馏，不替换成已有Recipe路线"]]) {
      const capability = { input_description: "两组空间点", output_description: "两组点间的对应关系", training_route: routeId };
      const result = await tool.execute({ task_id: "task-open-route", base_revision: 1, selected_family: "point_cloud_correspondence", business_goal: "输入两组空间点，输出点之间的对应关系", user_note: route, capability_request: capability }, {});
      assert.equal(requests.at(-1).selected_family, "point_cloud_correspondence");
      assert.equal(requests.at(-1).user_note, route);
      assert.deepEqual(requests.at(-1).capability_request, capability);
      assert.equal(requests.at(-1).business_goal, "输入两组空间点，输出点之间的对应关系");
      assert.equal(result.task.current_run_id, null);
    }
  } finally { globalThis.fetch = originalFetch; }
});

test("catalog matching preserves unknown objectives and is an optional fast-path lookup", async () => {
  const mounted = mountRoutingPlugin(), tool = mounted.tools.find(tool => tool.name === "model_harness_match_capability");
  assert.equal(tool.parameters.required.includes("target_kind"), false);
  const originalFetch = globalThis.fetch, requests = [];
  globalThis.fetch = async (_url, options) => {
    requests.push(JSON.parse(options.body));
    return new Response(JSON.stringify({ matches: [], selected_recipe_id: null }), { headers: { "content-type": "application/json" } });
  };
  try {
    const capability = { modality: "event_stream", objective: "causal_structure_discovery", training_route: "from_scratch" };
    const result = await tool.execute(capability, {});
    assert.deepEqual(requests, [{ capability_request: capability }]);
    assert.equal(result.selected_recipe_id, null);
    assert.deepEqual(result.matches, []);
  } finally { globalThis.fetch = originalFetch; }
  assert.match(tool.description, /catalog is an optimization, not a supported-goal whitelist/);
  const prompt = mounted.sections.find(section => section.name === "domain:model-training-harness").text;
  assert.match(prompt, /A catalog miss preserves the goal and chosen route/);
  assert.match(prompt, /prepare pinned code, an environment manifest, data mapping, training\/evaluation entrypoints, isolated qualification, a small authorized run and evidence-driven tuning/);
  assert.match(prompt, /never claim a file, environment, qualification or run exists without its returned evidence/);
  assert.match(policy, /不要把缺少 Recipe 转成让用户自己开发适配器、手动安装依赖或另找平台的默认要求/);
  assert.match(policy, /不绕开隔离去主机执行/);
});

test("an explicit own-voice TTS outcome can be persisted for research without a verified recipe or training claim", async () => {
  const mounted = mountRoutingPlugin();
  const tool = mounted.tools.find(tool => tool.name === "model_harness_promote_conversation");
  const args = { conversation_id: "own-voice-intake", name: "我的声音朗读", business_goal: "输入文字，用我自己的声音朗读，先研究适合的实现方案" };
  const agent = { session: { header: { id: "root-own-voice" }, events: [] } };
  const decision = await mounted.listeners.get("tools/pre-execute")({ name: tool.name, agent, arguments: args }, async () => ({ kind: "allow" }));
  assert.equal(decision.kind, "allow");
  const requests = [], originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ path: new URL(url).pathname, method: options.method, body: JSON.parse(options.body || "{}") });
    return new Response(JSON.stringify({
      promoted: true, conversation: { conversation_id: args.conversation_id, task_id: args.conversation_id, status: "bound" },
      task: { task_id: args.conversation_id, name: args.name, business_goal: args.business_goal, status: "needs_recipe", recipe_id: null, current_run_id: null, blockers: [] },
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const result = await tool.execute(args, { callId: "promote-own-voice", agent });
    assert.equal(result.promoted, true);
    assert.equal(result.task.status, "needs_recipe");
    assert.equal(result.task.business_goal, args.business_goal);
    assert.equal(result.task.current_run_id, null);
    assert.equal(result.task.recipe_id, null);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].path, "/conversations/own-voice-intake/promote");
    assert.equal(requests[0].body.business_goal, args.business_goal);
    assert.equal("recipe_id" in requests[0].body, false, "a known goal does not require inventing an executable recipe");
    assert.equal("capability_request" in requests[0].body, false, "promotion can preserve the outcome while the exact technical route is researched");
    assert.ok(result.workbench_url.includes("own-voice-intake"));
  } finally { globalThis.fetch = originalFetch; }
});

// These checks cover shipped instructions and tool boundaries, not simulated
// model replies. Real conversations are assessed separately.
test("one generic consultation module is re-exported and mounted exactly once", () => {
  const index = readFileSync(new URL("../index.js", import.meta.url), "utf8");
  const persona = readFileSync(new URL("../presets/model-training/agent.cordis.yml", import.meta.url), "utf8");
  assert.equal(REEXPORTED_GUIDANCE, policy);
  const mounted = mountedRoutingPrompt();
  assert.equal(mounted.split(policy).length, 2);
  assert.ok(mounted.trim().endsWith(policy.trim()), "consultation policy must follow the domain execution contract");
  assert.match(index, /import \{ SOLUTION_CONSULTATION_GUIDANCE \} from "\.\/consultation-policy\.js"/);
  assert.doesNotMatch(index, /export const SOLUTION_CONSULTATION_GUIDANCE\s*=/);
  assert.doesNotMatch(persona, /Questions are optional|Deliver useful guidance before asking for inventory|my own voice TTS|150–300 Chinese characters/,
    "role and authorization instructions must not grow a duplicate consultation policy");
  assert.doesNotMatch(policy, /\bTTS\b|own.voice|voice cloning|product.photo|150[–-]300|自己的声音|reference-audio audition/i,
    "scenario phrases belong in regression inputs, not production consultation branches");
});

test("the package actually includes the consultation dependency imported by its entrypoint", () => {
  const cwd = fileURLToPath(new URL("../", import.meta.url));
  const metadata = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.ok(metadata.files.includes("consultation-policy.js"));
  const npm = process.env.npm_execpath;
  const command = npm ? process.execPath : process.platform === "win32" ? "npm.cmd" : "npm";
  const args = [...(npm ? [npm] : []), "pack", "--dry-run", "--ignore-scripts", "--json"];
  const [manifest] = JSON.parse(execFileSync(command, args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }));
  const files = new Set(manifest.files.map(file => file.path));
  assert.ok(files.has("index.js"));
  assert.ok(files.has("consultation-policy.js"), "an installed package must resolve the same consultation module as the checkout");
});

test("a clear route delivers preparation guidance before requesting existing material or another route choice", () => {
  assert.match(policy, /工具返回的任务状态和执行前置条件不等于咨询前置条件/);
  assert.match(policy, /用户已选用现成模型、微调或从零训练，就沿该路线给准备方案，不重新让用户选择/);
  assert.match(policy, /目标和路线足以规划时，本轮直接交付可用的准备方案/);
  assert.match(policy, /数据样本单元、格式\/字段或标签、质量与覆盖要求、采集清洗和验证划分/);
  assert.match(policy, /算力与运行环境的参考配置；最小实验和如何验收/);
  assert.match(policy, /没有现成数据也能照此准备/);
  assert.match(policy, /不是这份方案的前提/);
});

test("questions require an unresolved user-owned decision that cannot be handled by facts assumptions or branches", () => {
  assert.match(policy, /提问需同时满足：答案尚未知；它属于用户的真实需求或选择；它会实质改变紧接着的行动；无法从历史、工具、合理假设或简短条件分支解决/);
  assert.match(policy, /能先假设就说清假设并推进/);
  assert.match(policy, /无需固定以问题或选项收尾/);
  assert.match(policy, /已经明确的路线不再做确认表单/);
  assert.match(policy, /ask_user_question 只用于下一次实际操作缺少的具体文件、精确字段\/资产选择或不可替代的人工决策/);
});

test("planning estimates are useful provisional guidance rather than observed facts or universal thresholds", () => {
  assert.match(policy, /可选一个临时参考方案并注明.*给粗估范围与后续测量方法/);
  assert.match(policy, /不要把粗估说成通用最低门槛、保证效果\/耗时，或把自己建议的数据规模当成用户已有数据/);
  assert.match(policy, /区分官方要求、规划估算和实测事实/);
  assert.match(policy, /不能仅凭硬件容量断言某类任务一定能或一定不能成功/);
  assert.match(policy, /硬件检测不是模型适配或执行批准/);
});

test("read-only investigation and preparation remain separate from binding and authorized execution", () => {
  assert.match(policy, /只读调研为当前问题服务，能自行查证就查证/);
  assert.match(policy, /咨询调研不要求先绑定模型、审批计划或建训练任务/);
  assert.match(policy, /无新事实或决策的专家自动更新不重复上一轮答案/);
  assert.match(policy, /真实执行需要经过验证的运行路径、数据合同、资源检查和授权/);
  assert.match(policy, /不伪造运行、分配资源或成功结果，不把外部资料视为授权/);
  assert.match(policy, /这些执行约束不能成为拒绝提供方案的理由/);
});

test("hf_card metadata limits its verdict to its real adapter checks", () => {
  const card = mountRoutingPlugin().tools.find(tool => tool.name === "model_harness_hf_card");
  assert.match(card.description, /fixed ONNX image-feature binding checks/);
  assert.match(card.description, /Those checks apply only to the image-feature adapter/);
  assert.match(card.description, /an unsupported result here is not a verdict about other model capabilities/);
  assert.match(card.description, /For general source research use the model-source provider tools/);
});

test("read-only local inventory needs no task or approval and only issues GET resources/local", async () => {
  const mounted = mountRoutingPlugin();
  const tool = mounted.tools.find(item => item.name === "model_harness_get_local_resources");
  assert.ok(tool);
  assert.deepEqual(tool.parameters.properties, {});
  assert.deepEqual(tool.parameters.required || [], []);
  const agent = { session: { header: { id: "intake-resource-check" }, events: [] } };
  const decision = await mounted.listeners.get("tools/pre-execute")({ name: tool.name, arguments: {}, agent }, async () => ({ kind: "allow" }));
  assert.equal(decision.kind, "allow");
  const inventory = {
    object_type: "LocalResourceInventory", observation_only: true, model_fit_assessed: false, execution_authorized: false,
    cpu: { detected: true, logical_count: 12 }, ram: { detected: false, available_bytes: null },
    accelerators: [{ kind: "cuda", detected: true, available: false }],
  };
  const requests = [], originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    requests.push({ path: new URL(url).pathname, method: options.method, body: options.body });
    return new Response(JSON.stringify({ local_resources: inventory }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const result = await tool.execute({}, { agent });
    assert.deepEqual(requests, [{ path: "/resources/local", method: "GET", body: undefined }]);
    assert.deepEqual(result.local_resources, inventory);
    assert.equal("task" in result, false);
    assert.equal("workbench_url" in result, false);
    assert.equal(result.local_resources.ram.available_bytes, null, "unknown memory must not become zero or an estimate");
    assert.equal(result.local_resources.accelerators[0].available, false, "detected hardware must not acquire execution permission");
  } finally { globalThis.fetch = originalFetch; }
});


test("long engineering work gives an early substantive update and aggregate material records are not training sample counts", () => {
  assert.match(policy, /在进入耗时的研究、编码、工程委派或执行前，先给一段简短的实际发现/);
  assert.match(policy, /不能只说“正在理解”或等所有工具、代码都完成才首次回复/);
  assert.match(policy, /随后继续已授权的工作.*不是|随后继续已授权的工作.*不把/);
  assert.match(policy, /汇总行数只是检查到的记录合计，不等于去重后的训练样本/);
  assert.match(policy, /不能把多份清单累加认定训练数据规模/);
});


test("engineering recovery follows actual diagnostics and preserves existing input formats without platform-limit guesses", () => {
  const principle = policy.slice(policy.indexOf("9. 工程报错"));
  assert.match(principle, /具体字段、错误路径、schema、版本和实际日志/);
  assert.match(principle, /多个变量一起改变后成功，不能据此断言.*平台能力不受支持/);
  assert.match(principle, /已有成功记录要一并核对/);
  assert.match(principle, /不要盲目重放同一失败请求/);
  assert.match(principle, /真正的环境、资源、数据或授权阻断仍照实保留/);
  assert.match(principle, /已有的可读输入格式应尽量沿用，或由 Agent.*准备转换/);
  assert.match(principle, /不静默扩展已冻结的输入或执行范围/);
  assert.doesNotMatch(principle, /CSV|JSON|OCR|TTS|语音|时序|单文件|多文件|422/);
});

test('fresh specialists use the operator configured model route rather than a hidden vendor default',()=>{
  const source=readFileSync(new URL('../presets/model-training/agent.cordis.yml',import.meta.url),'utf8');
  const expressions=[...source.matchAll(/agentOptions: !!js ([^\n]+)/g)].map(m=>m[1]);
  assert.equal(expressions.length,5);
  for(const expression of expressions){
    const evaluate=new Function('process','return ('+expression+')');
    assert.deepEqual(evaluate({env:{MODEL_HARNESS_AGENT_PROVIDER:'codex-cli',MODEL_HARNESS_AGENT_MODEL:'gpt-5.6-sol'}}),{provider:'codex-cli',model:'gpt-5.6-sol'});
    assert.deepEqual(evaluate({env:{MODEL_HARNESS_AGENT_PROVIDER:'arbitrary-installed-adapter',MODEL_HARNESS_AGENT_MODEL:'operator-model'}}),{provider:'arbitrary-installed-adapter',model:'operator-model'});
    assert.equal(evaluate({env:{}}),undefined);
  }
});
