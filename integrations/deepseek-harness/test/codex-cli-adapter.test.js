import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Context } from "@deepseek-ai/cordis";
import LlmRuntime from "@deepseek-ai/dsh-llm";
import { CodexCliAdapter, codexArgs, codexEnvironment, dynamicTools, responseHistory, omitHistoricalSource } from "../codex-cli-adapter.js";

const fixture = fileURLToPath(new URL("./fixtures/codex-rpc-fixture.js", import.meta.url));
const request = { provider: "codex-cli", model: "gpt-5.6-sol", messages: [{ role: "user", content: [{ type: "text", text: "fixture" }] }], tools: [{ name: "studio_echo", description: "probe", parameters: { type: "object" } }] };

test("history projection omits only older source bytes and retains user decisions, ids and hashes", () => {
  const original = { type: "function_call_output", call_id: "source-call", output: JSON.stringify({ proposal_id: "proposal-a", proposal_sha256: "a".repeat(64), execution_spec: { bundle_sha256: "b".repeat(64), bundle: { files: { "train.py": "large-old-source" } } } }) };
  const user = { type: "message", role: "user", content: [{ type: "input_text", text: "Keep my goal and gate 0.95" }] };
  const recent = { ...original, call_id: "current-source" };
  const found = omitHistoricalSource([original, user, recent], 1);
  assert.equal(found[1], user); assert.equal(found[2], recent);
  const older = JSON.parse(found[0].output); assert.equal(older.proposal_sha256, "a".repeat(64)); assert.equal(older.execution_spec.bundle_sha256, "b".repeat(64)); assert.match(older.execution_spec.bundle.files["train.py"], /re-read/); assert.equal(JSON.parse(original.output).execution_spec.bundle.files["train.py"], "large-old-source");
});
function route(mode, timeoutMs = 2000) {
  const children = [], launches = [];
  const adapter = new CodexCliAdapter({ timeoutMs, spawn(bin, args, options) {
    launches.push({ bin, args, options });
    const child = spawn(process.execPath, [fixture], { ...options, env: { ...options.env, SMS_CODEX_FIXTURE: mode } }); children.push(child); return child;
  } });
  return { adapter, children, launches };
}
async function collect(adapter, options = request) { const chunks = []; for await (const chunk of adapter.stream(options)) chunks.push(chunk); return chunks; }

test("registered metadata passes the actual DSH model/effort consumer", async () => {
  const ctx = new Context(); const runtime = new LlmRuntime(ctx); const dispose = runtime.registerAdapter(["codex-cli"], new CodexCliAdapter());
  try { const model = await runtime.resolveModelInfo("codex-cli", "gpt-5.6-sol"); assert.equal(model.reasoning.defaultEffort, "low"); assert.equal(model.context.contextWindow, 128000); assert.ok(model.reasoning.efforts.some(e => e.id === "low")); } finally { dispose(); }
});

test("CLI child excludes API credentials and bridge grant; host shell/plugins disabled without modifying parent environment", () => {
  const source = { HOME: "/home/example", CODEX_HOME: "/existing-login", OPENAI_API_KEY: "private", CODEX_API_KEY: "private", DEEPSEEK_API_KEY: "private", MODEL_HARNESS_AGENT_BRIDGE_TOKEN: "private" };
  assert.deepEqual(codexEnvironment(source), { HOME: source.HOME, CODEX_HOME: source.CODEX_HOME }); assert.equal(source.OPENAI_API_KEY, "private");
  const args = codexArgs(["existing_server"]); assert.ok(args.includes("features.shell_tool=false")); assert.ok(args.includes("features.unified_exec=false")); assert.ok(args.includes("features.apps=false")); assert.ok(args.includes("mcp_servers.existing_server.enabled=false")); assert.ok(args.includes("model_context_window=1050000")); assert.ok(args.includes("model_auto_compact_token_limit=1000000000")); assert.throws(() => codexArgs(["bad.name"]), /configuration/);
});

test("native history keeps roles, original source bytes, call IDs and error results", async () => {
  const { aliases, specs } = dynamicTools([{ name: "tool/with/slash", description: "real", parameters: { type: "object" } }]);
  assert.equal(specs[0].name, "studio_tool_0");
  const code = 'print("你好")\n'; const args = JSON.stringify({ files: { "run.py": code } });
  const result = await responseHistory([{ role: "system", content: [{ type: "text", text: "trusted policy" }] }, { role: "assistant", content: [{ type: "tool-call", id: "call-1", name: "tool/with/slash", arguments: args }] }, { role: "user", content: [{ type: "tool-result", toolCallId: "call-1", isError: true, content: [{ type: "text", text: "qualification_failed" }] }] }], aliases);
  assert.deepEqual(result.system, ["trusted policy"]); assert.equal(result.history[0].arguments, args); assert.equal(JSON.parse(result.history[0].arguments).files["run.py"], code); assert.equal(result.history[0].name, "studio_tool_0"); assert.equal(result.history[1].call_id, "call-1"); assert.equal(result.history[1].output, "qualification_failed");
});

test("image history requires a real resolver rather than silently losing content", async () => {
  const messages = [{ role: "user", content: [{ type: "image", attachment: { id: "observed" } }] }];
  await assert.rejects(responseHistory(messages, new Map()), /attachment service/);
  const result = await responseHistory(messages, new Map(), { async readImage(ref) { assert.equal(ref.id, "observed"); return { ref: { mediaType: "image/png" }, data: Uint8Array.of(1, 2) }; } });
  assert.equal(result.history[0].content[0].image_url, "data:image/png;base64,AQI=");
});

test("stdio text/usage stream completes once and releases the owned CLI process", async () => {
  const r = route("text"), chunks = await collect(r.adapter);
  assert.equal(chunks.filter(c => c.type === "text-delta").map(c => c.text).join(""), "真实回复"); assert.equal(chunks.filter(c => c.type === "block-end").length, 1); assert.deepEqual(chunks.at(-1), { type: "finish", reason: { kind: "stop" } });
  assert.deepEqual(chunks.find(c => c.type === "usage").usage, { inputTokens: 30, outputTokens: 10, cacheReadTokens: 70, reasoningTokens: 3 }); assert.ok(r.children[0].exitCode !== null || r.children[0].signalCode !== null); assert.equal(r.launches[0].options.detached, true);
});

test("parallel native tool requests preserve identities and return to outer approval loop without execution", async () => {
  const r = route("tools"), chunks = await collect(r.adapter); const calls = chunks.filter(c => c.type === "block-end").map(c => c.block);
  assert.deepEqual(calls.map(c => c.id), ["call-1", "call-2"]); assert.deepEqual(calls.map(c => JSON.parse(c.arguments)), [{ value: 1 }, { value: 2 }]); assert.equal(chunks.at(-1).reason.kind, "tool-calls"); assert.ok(r.children[0].exitCode !== null || r.children[0].signalCode !== null);
});

test("API-key login, native operations, unknown tool names and failed turns fail closed", async () => {
  for (const [mode, message] of [["api", /ChatGPT login/], ["native", /native host operation/], ["foreign", /outside the current role/], ["failed", /Provider failed/]]) {
    const r = route(mode); await assert.rejects(collect(r.adapter), message); assert.ok(r.children[0].exitCode !== null || r.children[0].signalCode !== null);
  }
});

test("caller cancellation and timeout stop their own pending inference subprocess", async () => {
  const controller = new AbortController(), r = route("hang"); const pending = collect(r.adapter, { ...request, signal: controller.signal }); setTimeout(() => controller.abort(), 60);
  await assert.rejects(pending, /cancelled/); assert.ok(r.children[0].exitCode !== null || r.children[0].signalCode !== null);
  const timed = route("hang", 100); await assert.rejects(collect(timed.adapter), /timed out/); assert.ok(timed.children[0].exitCode !== null || timed.children[0].signalCode !== null);
});

test("unavailable CLI binary fails without hanging teardown", async () => {
  const adapter = new CodexCliAdapter({ bin: "/nonexistent/studio-codex", timeoutMs: 500 }); await assert.rejects(collect(adapter), /could not start|exited|input closed/);
});

test("over-budget input uses the native DSH compaction recovery code and does not launch a CLI", async () => {
  let launched = false;
  const adapter = new CodexCliAdapter({spawn(){launched=true; throw new Error('must not launch');}});
  await assert.rejects(collect(adapter,{...request,messages:[{role:'user',content:[{type:'text',text:'x'.repeat(800000)}]}]}),error=>error.code==='CONTEXT_WINDOW_EXCEEDED');
  assert.equal(launched,false);
});
