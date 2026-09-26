import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const css = readFileSync(new URL("../../../model_harness/web/visual-system.css", import.meta.url), "utf8");

// Static style contracts only. Browser layout/overflow and interaction require
// the separate 1280 / 1440 / 1920 PC acceptance run.
function block(source, selector) {
  const start = source.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `missing style contract: ${selector}`);
  const opening = source.indexOf("{", start);
  let depth = 1;
  for (let index = opening + 1; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) return source.slice(opening + 1, index);
  }
  assert.fail(`unclosed style contract: ${selector}`);
}

const pc = block(css, "@media (min-width: 900px)");

test("compact PC keeps report non-modal and reserves the input footer in the viewport", () => {
  const desktop = block(css, "@media (min-width: 900px)");
  assert.match(desktop, /body \.app-shell \{ height: 100dvh; min-height: 0; grid-template-rows:\s*minmax\(0, 1fr\)/);
  assert.match(block(desktop, "body .conversation-main"), /height:\s*100dvh; min-height:\s*0; overflow:\s*hidden/);
  assert.match(block(desktop, "body .conversation"), /min-height:\s*0; flex:\s*1 1 0; overflow-y:\s*auto/);
  assert.match(block(desktop, "body .conversation-main > .composer-wrap"), /flex:\s*0 0 auto/);
  const compact = block(css, "@media (min-width: 900px) and (max-width: 1279px)");
  assert.match(block(compact, 'body[data-workspace="open"] .app-shell'), /minmax\(0, 1fr\) clamp\(340px, 40vw, 480px\)/);
  assert.match(block(compact, "body .inspector"), /position:\s*relative/);
  assert.match(block(compact, "body .inspector-scrim:not([hidden])"), /display:\s*none !important/);
});

test("PC split tracks reserve usable conversation and result widths without a fixed center minimum", () => {
  const tokens = block(pc, "body");
  const sidebar = Number(tokens.match(/--sidebar-width:\s*(\d+)px/)[1]);
  const [, minimum, percent, maximum] = tokens.match(/--workspace-width:\s*clamp\((\d+)px,\s*(\d+)vw,\s*(\d+)px\)/).map(Number);
  const shell = block(pc, 'body[data-workspace="open"] .app-shell');
  assert.match(shell, /grid-template-columns:\s*var\(--sidebar-width\) minmax\(0, 1fr\) var\(--workspace-width\)/);
  for (const width of [1280, 1440, 1920]) {
    const result = Math.max(minimum, Math.min(width * percent / 100, maximum));
    const conversation = width - sidebar - result;
    assert.ok(conversation >= 480, `${width}: conversation track cannot read comfortably`);
    assert.ok(result >= 400, `${width}: result track cannot read comfortably`);
    assert.equal(sidebar + conversation + result, width);
  }
  assert.doesNotMatch(pc, /minmax\(560px/);
});

test("PC message styling preserves complete prose instead of clipping or collapsing it", () => {
  for (const selector of ["body .message-copy", "body .ai-turn-status b"]) {
    const rule = block(pc, selector);
    assert.doesNotMatch(rule, /line-clamp|max-height|display:\s*none|overflow:\s*hidden/);
  }
  const reference = block(css, "body .message-context-reference pre");
  assert.match(reference, /white-space:\s*pre-wrap/);
  assert.match(reference, /overflow-wrap:\s*anywhere/);
  assert.doesNotMatch(reference, /max-height|line-clamp/);
});

test("trial report uses a flat readable facts and raw-output contract", () => {
  assert.match(block(css, "body .model-trial-report-facts"), /repeat\(2, minmax\(0, 1fr\)\)/);
  assert.match(block(css, "body .model-trial-report-facts dd"), /overflow-wrap:\s*anywhere/);
  assert.match(block(css, "body .model-trial-output-list li"), /minmax\(0, 1fr\)/);
  assert.match(block(css, "body .model-trial-report-evidence pre"), /overflow:\s*auto/);
  assert.match(block(css, "body .model-trial-report-evidence pre"), /max-width:\s*100%/);
  assert.match(block(css, 'body .model-trial-report-record[aria-pressed="true"]'), /background:\s*var\(--surface-muted\)/);
  assert.match(block(css, "body .model-trial-report [hidden]"), /display:\s*none/);
});

test("composer interruption keeps copy flexible and the stop control explicit", () => {
  assert.match(block(pc, "body .composer-delivery"), /grid-template-columns:\s*minmax\(0, 1fr\) auto/);
  assert.match(block(pc, "body .composer-delivery-copy"), /overflow-wrap:\s*anywhere/);
  assert.match(block(pc, "body .composer-stop-modify"), /min-height:\s*34px/);
  assert.match(block(pc, "body .composer-stop-modify:disabled"), /cursor:\s*not-allowed/);
  assert.match(block(pc, "body .composer-delivery[hidden]"), /display:\s*none/);
});

test("desktop controls and message shapes follow a restrained working surface", () => {
  assert.match(block(pc, "body .new-task-button"), /justify-content:\s*flex-start/);
  assert.match(block(pc, "body .new-task-button"), /border-radius:\s*8px/);
  assert.match(block(pc, 'body .message[data-role="user"] .message-copy'), /border-radius:\s*14px/);
  assert.match(block(pc, "body .composer"), /min-height:\s*104px/);
  assert.match(block(pc, "body .composer"), /border-radius:\s*14px/);
  assert.match(block(pc, "body .send-button"), /width:\s*36px; height:\s*36px/);
  assert.match(block(pc, "body .topbar"), /min-height:\s*56px/);
  for (const selector of ["body .conversation", "body .inspector"]) {
    assert.match(block(pc, selector), /overscroll-behavior-y:\s*contain/);
    assert.match(block(pc, selector), /scrollbar-gutter:\s*stable/);
  }
});

test("desktop prose aligns with the input without suppressing the turn identity", () => {
  assert.match(block(pc, "body .ai-turn-main"), /display:\s*contents/);
  assert.match(block(pc, "body .ai-turn-header"), /grid-column:\s*2/);
  assert.match(block(pc, "body .ai-turn-content"), /grid-column:\s*1 \/ -1/);
  assert.doesNotMatch(block(pc, "body .ai-turn-header"), /display:\s*none/);
  assert.doesNotMatch(pc, /\.message-meta[^}]*display:\s*none/);
});

test("desktop deduplication targets healthy connection and read-only trial shortcuts only", () => {
  assert.match(block(pc, 'body .composer-mode[data-state="agent"]'), /display:\s*none/);
  assert.doesNotMatch(pc, /\.composer-mode\[data-state="(?:checking|local|unavailable)"\][^}]*display:\s*none/);
  assert.match(block(pc, 'body[data-view="task"] .product-boundary,\n  body[data-view="conversation"] .product-boundary'), /display:\s*none/);
  assert.match(block(pc, 'body[data-workspace="open"] .agent-checkpoint[data-kind="model-trial-summary"][data-read-error="false"]'), /display:\s*none/);
  assert.match(block(pc, 'body .agent-checkpoint[data-kind="model-trial-summary"][data-read-error="false"] > #agentCheckpointSummary'), /display:\s*none/);
  assert.doesNotMatch(block(pc, 'body .agent-checkpoint[data-kind="model-trial-summary"][data-read-error="true"] > #agentCheckpointSummary'), /display:\s*none/);
  assert.doesNotMatch(pc, /body\[data-workspace="open"\] \.agent-checkpoint\[data-kind="model-trial-summary"\]\s*\{/);
  assert.match(block(pc, 'body .agent-checkpoint[data-kind="model-trial-summary"] .checkpoint-workspace-button small'), /overflow-wrap:\s*anywhere/);
  assert.doesNotMatch(pc, /body \.agent-checkpoint\s*\{[^}]*display:\s*none/);
  assert.doesNotMatch(pc, /\.(?:human-checkpoint|human-choice|truth-notice|composer-notice)[^}]*display:\s*none/);
});

test("the new desktop visual layer does not introduce a mobile redesign or new logo", () => {
  assert.match(pc, /--surface-muted:\s*#f1f1f3/);
  assert.match(css, /--brand:\s*#5a4fd6/);
  assert.doesNotMatch(pc, /@media.*max-width|brand-mark\s*\{/);
  assert.match(block(pc, "body .inspector"), /background:\s*var\(--surface\)/);
  assert.match(block(pc, "body .inspector"), /box-shadow:\s*none/);
});
