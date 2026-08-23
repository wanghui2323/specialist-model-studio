# ADR-001 · One product for research-to-model work

- Status: **accepted; brand migration completed, legacy archival not approved**
- Date: 2026-08-23
- Current repository: `wanghui2323/specialist-model-studio`
- Legacy repository reviewed: `wanghui2323/Universal-SciAgent`
- Legacy commit audited: `d7e7b0509ae8cb701d6e9ccc454ed998208533cc`

## Decision

Build one user-facing product and one active source-of-truth repository for the
path from research evidence to a deliverable specialist model.

The current Model Harness repository becomes the consolidation target because
its root object is already the persisted `TrainingTask` and it owns source
binding, data, plans, approvals, runs, evaluation and artifacts. We will migrate
only the useful research-provider and evidence ideas from Universal-SciAgent.
We will not move Model Harness into the old Science repository and we will not
import the old repository wholesale.

The confirmed public product name is **Specialist Model Studio** and the
repository slug is `specialist-model-studio`. The brand and GitHub repository
rename are complete. The
internal `model_harness` package and `small-model-harness` CLI remain compatible
engine names during migration.

Universal-SciAgent stays unchanged until the new Research workstream passes its
own live acceptance. Archiving the legacy repository remains a separate external
action and has not been approved.

## Why this direction

The old repository's real deployment entry is one VeADK root agent with arXiv,
Semantic Scholar, PubMed and PDF tools, not the multi-agent system implied by
the README:

- [`agent.py` deployment entry](https://github.com/wanghui2323/Universal-SciAgent/blob/d7e7b0509ae8cb701d6e9ccc454ed998208533cc/agent.py#L139-L162)
- [`ResearchWorkflow` role prototypes](https://github.com/wanghui2323/Universal-SciAgent/blob/d7e7b0509ae8cb701d6e9ccc454ed998208533cc/backend/workflows/research_workflow.py#L84-L223)

`MasterAgent`, `UniversalSciAgentSystem` and `ResearchWorkflow` form three
overlapping orchestrators and are not connected to one durable task lifecycle.
Copying the repository would introduce a second runtime, a second state store
and duplicate orchestration without closing the model-training loop.

The parts worth preserving are the real paper-provider integrations, result
normalization ideas and research-role decomposition:

- [`veadk_tools.py` paper providers](https://github.com/wanghui2323/Universal-SciAgent/blob/d7e7b0509ae8cb701d6e9ccc454ed998208533cc/backend/tools/veadk_tools.py#L41-L247)
- [`LiteratureAgent` concurrent search](https://github.com/wanghui2323/Universal-SciAgent/blob/d7e7b0509ae8cb701d6e9ccc454ed998208533cc/backend/agents/literature_agent.py#L107-L244)

## Product boundary

The primary product remains specialist-model creation:

```text
question or business need
  -> research evidence
  -> model / code / dataset candidates
  -> immutable source and data contracts
  -> resource-feasible plan
  -> controlled training
  -> evaluation and delivery
```

Paper research that changes model, data or evaluation decisions belongs inside
the `TrainingTask`. Pure general research with no model-building downstream is
not forced into a fake training task; it may later use the same Research plugin
in standalone mode.

## Agent architecture

The user talks to one Training Orchestrator. Specialist roles operate behind
that one conversation and communicate only through persisted, versioned
objects. The UI does not simulate a group chat between fictional agents.

| Role | Owns | Cannot do |
| --- | --- | --- |
| Training Orchestrator | Clarification, job routing, pauses, human checkpoints | Invent tool results or silently approve work |
| Research & Source Agent | Papers, HF/GitHub/data-source search, evidence and asset links | Bind a source or treat a candidate as compatible |
| Data & Experiment Agent | Data requirements, quality diagnosis, hypotheses and ablation design | Lower quality gates or start a run |
| Resource & Safety Agent | Compute fit, licenses, dependency and untrusted-content policy | Override a blocker |
| Build & Training Agent | Recipe/build plan, isolated qualification and real runs | Execute third-party code outside an approved boundary |
| Evaluation & Delivery Agent | Metrics, failure analysis, inference checks, reports and bundles | Mark a failed gate as release-ready |

Each role is a permission profile over tools and objects, not a new source of
truth. The existing Workspace remains authoritative.

## Persisted research objects

```text
TrainingTask
  └─ TaskSpecRevision
      ├─ ResearchQueryRevision
      ├─ ResearchSearchRun
      ├─ PaperRecord
      ├─ EvidenceClaim
      ├─ ResearchAssetLink
      └─ ResearchBrief
```

- `ResearchQueryRevision`: query intent, inclusion/exclusion rules, requested
  providers, date/language filters and parent revision.
- `ResearchSearchRun`: provider, exact query, lifecycle status, typed error,
  result count, raw-response digest and timing.
- `PaperRecord`: normalized DOI/arXiv/PMID/Semantic Scholar identity, metadata,
  source URL, snapshot digest and access/license facts.
- `EvidenceClaim`: claim type, concise summary, page/section/field locator,
  evidence hash, extractor version and human-confirmation state.
- `ResearchAssetLink`: typed `implements`, `trains_on`, `evaluated_on`, `extends`
  or `compares_with` link to a paper, model, repository or dataset.
- `ResearchBrief`: immutable synthesis bound to the exact TaskSpec and evidence
  set. A requirement revision supersedes it without deleting history.

## Provider and tool contracts

```text
ResearchProvider.search(query_revision) -> ProviderSearchResult
EvidenceExtractor.extract(paper_snapshot) -> EvidenceClaim[]
AssetLinker.link(claims, source_candidates) -> ResearchAssetLink[]
```

DeepSeek Harness exposes the workstream through explicit task tools:

```text
model_harness_plan_research
model_harness_search_papers
model_harness_get_paper_evidence
model_harness_link_research_assets
model_harness_approve_research_brief
```

Only human-approved asset links can feed the existing
`ModelSourceBinding -> SourceSnapshot -> RepositoryAnalysis -> TrainingPlan`
chain.

## Migration plan

### R0 · Contract and provider slice

- Add the six research objects and lifecycle schemas.
- Implement arXiv, Semantic Scholar and PubMed as provider adapters without
  VeADK or Chroma.
- Persist populated, empty, partial-provider-failure and all-provider-failure
  searches distinctly.
- Add controlled live tests that can be disabled without making local tests
  contact the network.

### R1 · Evidence and asset links

- Normalize paper identities and deduplicate provider results.
- Snapshot metadata before claim extraction.
- Produce locator-backed claims and model/code/dataset links.
- Treat paper/PDF text as untrusted content; it cannot issue tool commands.

### R2 · Conversation and workspace

- Ask whether research evidence is needed only when it can change a decision.
- Show search as real persisted tool events in the conversation.
- Show papers, claims, conflicts and asset links in the adaptive workspace.
- Require a Research Brief checkpoint before asset links affect source ranking.

### R3 · Legacy transition

- Reproduce at least one real Universal-SciAgent literature workflow inside the
  new task lifecycle with source-linked evidence.
- Publish a migration map and preserve Apache notices for copied/modified code.
- Only then request approval to rename the main repository and archive the old
  repository with a migration notice.

## Acceptance gates

- A real paper query returns traceable provider records and a persisted search
  run; empty results are not provider failures.
- One provider can fail while other candidates remain usable and visibly
  degraded.
- A complete provider outage persists the exact typed failure and explicit
  retry target.
- Every claim used in a recommendation has a source identity, locator and
  digest; unsupported claims are visibly unverified.
- Paper text cannot invoke tools, alter a TaskSpec or approve a plan.
- A paper-to-model link remains a candidate until a human approves it and the
  existing source-binding gates pass.
- Refresh/restart preserves queries, attempts, claims, links, approvals and
  blockers without synthesizing dialogue.
- At least one paper -> HF/GitHub asset -> approved Research Brief path is
  verified in a real browser before legacy archival.

## Rejected approaches

### Keep two active products indefinitely

Rejected because it duplicates conversation, task state, retrieval records,
runtime and UI while forcing the user to transfer evidence manually.

### Move Model Harness into Universal-SciAgent

Rejected because the old deployed entry is not the durable multi-agent system
we need and does not own model-source binding, plans, runs or artifacts.

### Copy the entire old repository into the new one

Rejected because VeADK, AgentKit, Chroma and three overlapping orchestrators
would create a second system rather than a plugin.

## Security and licensing

- Universal-SciAgent is Apache-2.0 while Model Harness is currently MIT. Any
  copied or modified Apache source retains its license, notice and modification
  statement.
- Paper metadata, abstracts, full text, datasets, model weights and repositories
  each retain their own rights; the software license does not grant content
  redistribution rights.
- The old PDF fetcher accepts arbitrary URLs/local paths and lacks adequate
  host, MIME, size, page and SSRF controls, so it will not be copied directly:
  [`veadk_tools.py` PDF path](https://github.com/wanghui2323/Universal-SciAgent/blob/d7e7b0509ae8cb701d6e9ccc454ed998208533cc/backend/tools/veadk_tools.py#L254-L309).
- Current key-method extraction is incomplete and will not be treated as a
  working capability:
  [`literature_agent.py` incomplete extraction](https://github.com/wanghui2323/Universal-SciAgent/blob/d7e7b0509ae8cb701d6e9ccc454ed998208533cc/backend/agents/literature_agent.py#L319-L355).
