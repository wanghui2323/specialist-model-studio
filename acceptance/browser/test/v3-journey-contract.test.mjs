import assert from "node:assert/strict";
import test from "node:test";

import {
  assertRequiredRoutes,
  parseArgs,
  snapshotV3Lineage,
  v3RequiredRouteContracts,
} from "../collect-browser.mjs";

const common = [
  "--base-url", "http://127.0.0.1:8765",
  "--output-dir", "/tmp/v3-browser-output",
  "--source-commit", "a".repeat(40),
  "--producer-run-id", "evidence-v3-browser-contract",
  "--chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
];

test("v3 mode requires parameterized public source inputs", () => {
  const parsed = parseArgs([
    ...common,
    "--mode", "v3-journey",
    "--business-goal", "训练一个公开仓库中的图像模型",
    "--task-family", "custom",
    "--provider", "github",
    "--query", "owner repository",
    "--repository", "owner/repository",
    "--revision", "main",
    "--entrypoint", "scripts/train.py",
    "--metric", "accuracy",
    "--base-image-digest", `sha256:${"b".repeat(64)}`,
  ]);
  assert.equal(parsed.mode, "v3-journey");
  assert.equal(parsed["timeout-ms"], 180_000);
  assert.equal(parsed.repository, "owner/repository");
});

test("v3 mode fails closed on missing or unsafe inputs", () => {
  assert.throws(() => parseArgs([...common, "--mode", "v3-journey"]), /missing --business-goal/);
  assert.throws(() => parseArgs([
    ...common,
    "--mode", "v3-journey",
    "--business-goal", "goal",
    "--task-family", "custom",
    "--provider", "github",
    "--query", "query",
    "--repository", "owner/repo",
    "--revision", "main",
    "--entrypoint", "../train.py",
  ]), /safe repository-relative path/);
  assert.throws(() => parseArgs([
    ...common,
    "--mode", "v3-journey",
    "--business-goal", "goal",
    "--task-family", "custom",
    "--provider", "github",
    "--query", "query",
    "--repository", "owner/repo",
    "--revision", "main",
    "--base-image-digest", "python:3.12",
  ]), /base image digest/);
});

test("required routes accept only the exact task-owned mutation set", () => {
  const taskId = "task-v3-browser";
  const contracts = v3RequiredRouteContracts(
    taskId,
    { resolution_id: "resolution-1" },
    { base_analysis_id: "analysis-base" },
    { training_plan_revision_id: "plan-1" },
    { manualMapping: true },
  );
  const network = contracts.flatMap((contract) => {
    const count = contract.name === "resource_checked" ? 2 : 1;
    return Array.from({ length: count }, () => ({
      kind: "response",
      method: contract.method,
      path: contract.path,
      status: contract.statuses[0],
    }));
  });
  const result = assertRequiredRoutes(network, contracts);
  assert.equal(result.source_bound[0].status, 202);
  assert.equal(result.analysis_mapped[0].status, 201);
  assert.equal(result.resource_checked.length, 2);

  assert.throws(() => assertRequiredRoutes([
    ...network,
    { kind: "response", method: "POST", path: `/tasks/${taskId}/runs`, status: 201 },
  ], contracts), /unexpected mutating browser routes/);
});

test("lineage snapshot requires exact immutable IDs and digests", () => {
  const digest = "c".repeat(64);
  const task = {
    task_id: "task-v3-browser",
    model_binding: {
      resolution_id: "resolution-1",
      resolution_digest: digest,
      requested_revision: "main",
      resolved_commit: "d".repeat(40),
      binding_revision_id: "binding-1",
      content_digest: digest,
      snapshot_id: "snapshot-1",
      snapshot_digest: digest,
      analysis_digest: digest,
    },
    repository_analysis: {
      analysis_id: "analysis-1",
      analysis_digest: digest,
      analyzer_version: "repository-analysis/0.4",
    },
    training_plan: {
      plan: {
        training_plan_revision_id: "plan-1",
        plan_sha256: digest,
        revision: 1,
      },
      latest_approval: {
        approval_id: "approval-1",
        approval_sha256: digest,
        digest,
      },
    },
    resource_feasibility: {
      resource_probe: { resource_probe_id: "probe-1", probe_sha256: digest },
      blockers: [{
        active: true,
        blocker_id: "blocker-1",
        content_digest: digest,
        stage: "environment_lock",
        code: "blocked_environment",
        detector: "container_runtime_probe",
      }],
    },
  };
  const snapshot = snapshotV3Lineage(task);
  assert.equal(snapshot.plan.id, "plan-1");
  assert.equal(snapshot.blocker.id, "blocker-1");
  assert.equal(snapshot.approval.plan_digest, digest);

  task.resource_feasibility.blockers = [];
  assert.throws(() => snapshotV3Lineage(task), /active resource blocker/);
});
