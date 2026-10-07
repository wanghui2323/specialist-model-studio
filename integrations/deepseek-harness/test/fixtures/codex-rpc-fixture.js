import { createInterface } from "node:readline";
const mode = process.env.SMS_CODEX_FIXTURE || "text";
const send = (message) => process.stdout.write(JSON.stringify(message) + "\n");
createInterface({ input: process.stdin }).on("line", (line) => {
  const request = JSON.parse(line);
  if (request.method === "initialize") return send({ id: request.id, result: {} });
  if (request.method === "initialized") return;
  if (request.method === "account/read") return send({ id: request.id, result: { account: { type: mode === "api" ? "apiKey" : "chatgpt" } } });
  if (request.method === "thread/start") return send({ id: request.id, result: { thread: { id: "probe-thread" }, model: request.params.model } });
  if (request.method === "thread/inject_items") return send({ id: request.id, result: {} });
  if (request.method === "turn/interrupt") return send({ id: request.id, result: {} });
  if (request.method !== "turn/start") return send({ id: request.id, error: { message: "Unexpected request" } });
  send({ id: request.id, result: { turn: { id: "probe-turn" } } });
  if (mode === "hang") return;
  if (mode === "native") return send({ id: "host-request", method: "item/commandExecution/requestApproval", params: { threadId: "probe-thread" } });
  if (mode === "foreign") return send({ id: "tool-request", method: "item/tool/call", params: { threadId: "probe-thread", callId: "call-foreign", tool: "unregistered", arguments: {} } });
  if (mode === "tools") {
    for (const n of [1, 2]) send({ id: `tool-request-${n}`, method: "item/tool/call", params: { threadId: "probe-thread", callId: `call-${n}`, tool: "studio_echo", arguments: { value: n } } });
    return;
  }
  if (mode === "failed") return send({ method: "turn/completed", params: { threadId: "probe-thread", turn: { id: "probe-turn", status: "failed", error: { message: "Provider failed" } } } });
  for (const delta of ["真实", "回复"]) send({ method: "item/agentMessage/delta", params: { threadId: "probe-thread", itemId: "message-1", delta } });
  send({ method: "item/completed", params: { threadId: "probe-thread", item: { id: "message-1", type: "agentMessage", text: "真实回复" } } });
  send({ method: "thread/tokenUsage/updated", params: { threadId: "probe-thread", tokenUsage: { last: { inputTokens: 100, cachedInputTokens: 70, outputTokens: 10, reasoningOutputTokens: 3 } } } });
  send({ method: "turn/completed", params: { threadId: "probe-thread", turn: { id: "probe-turn", status: "completed" } } });
});
