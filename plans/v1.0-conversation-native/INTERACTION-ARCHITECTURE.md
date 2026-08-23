# Specialist Model Studio Conversation-Native Interaction Architecture

## Product sentence

The user describes a specialist-model capability in one thread. The agent turns
that intent into an auditable task, searches public model sources, pauses at
human decision points, prepares data and an immutable plan, runs only inside a
verified boundary, and returns evidence-backed evaluation and artifacts.

## One narrative, three surfaces

| Surface | Owns | Must not own |
| --- | --- | --- |
| Task sidebar | Thread switching, new task, archive, coarse live state | Training forms or duplicate progress |
| Conversation | User intent, agent decision summaries, tool events, questions, approvals, intervention | Hidden chain-of-thought or invented progress |
| Adaptive workspace | The currently selected source, dataset, run, evaluation, and artifact evidence | A second competing workflow |

The workspace is absent before a task exists, collapsed during simple dialogue,
and opened when an artifact benefits from inspection. Closing it never changes
task state. On mobile it is a sheet, not a third fixed column.

## Reference experiment: WorkBuddy, not a skin copy

On 2026-08-23 we used the installed WorkBuddy 5.3.14 against an empty local
workspace and asked it to plan a Mandarin speech-to-text training task without
downloading or training. Its first response demonstrated the useful control
pattern: ask one implementation-changing question, offer concrete choices, and
explain why the answer changes model selection. It completed five sequential
clarifications covering language, Apple Silicon/16 GB/MPS constraints, data
availability, multi-speaker meeting audio, and timestamp/punctuation output.
We keep that pattern.

The same experiment also exposed patterns that Specialist Model Studio must not copy. A
prompt-enhancement action expanded a one-line language answer into an unrelated
long prompt. Submitting an edited answer twice produced
`Failed to execute 'removeChild' on 'Node'`; reset restored the expanded prompt
instead of the user's concise draft. One generation failed with HTTP 499 and a
Trace ID; explicit Retry recovered to the fifth question, but inserted a generic
`请继续完成未完成的任务。` user message rather than preserving the failed request's
identity. These are concrete recovery failures, not visual preferences. Model
Harness therefore:

- never rewrites a short answer into a larger hidden instruction;
- asks one question at a time and persists the selected answer as task evidence;
- distinguishes an active request, a queued request, and a stopped request;
- persists the exact failed operation, typed error, trace identifier and retry
  target; retry never invents a replacement user message;
- keeps the user's original draft editable across failure and reset;
- keeps the right workspace evidence-only and opens it on demand;
- preserves a structured local workflow when Agent Runtime is unavailable.

After recovery, WorkBuddy did complete the research-only checkpoint: it returned
three Hugging Face candidates, created a 6.2 KB `asr-model-research.md` artifact,
showed 15 references in the UI, and stopped before download or training. The
artifact itself contained direct model links but did not embed the 15-source
ledger shown in the UI. Specialist Model Studio therefore binds source records and
evidence digests to the persisted report/artifact instead of leaving provenance
in a separate transient surface.

The visual reference is a neutral task surface with restrained purple for
agent decisions and green reserved for verified passes. The brand promise stays
specific: **Specialist Model Studio turns a conversation into real data, real
runs, and reviewable model evidence.**

## Conversation checkpoints

Each checkpoint is rendered from persisted backend facts and is stable after a
refresh. It is not a scripted animation.

1. **Requirement formation** — the assistant asks one question that can change
   the training implementation, provides 2–4 backend-owned choices plus a free
   description path, then persists the confirmed requirement version. Technical
   TaskSpec fields remain available in the workspace instead of dominating the
   conversation.
2. **Source discovery** — official Hugging Face/GitHub search appears as a real
   tool event. Candidate cards remain in the thread until a human selects one.
3. **Immutable source** — requested revision, resolved commit, license policy,
   and manifest are shown before the second explicit binding approval.
4. **Data preparation** — the thread asks for the adapter-compatible dataset,
   then shows the persisted inspection report and rejected-file facts.
5. **Plan approval** — the exact entrypoint, resource budget, execution boundary,
   lineage, and plan digest are shown. A change creates a child revision; it
   never mutates an approved plan.
6. **Training** — the thread remains writable while the workspace shows real
   backend run events. Agent cancellation and run cancellation stay separate.
7. **Evaluation and delivery** — the assistant summarizes the verdict; the
   workspace contains metrics, failure samples, run history, inference checks,
   and artifact bundles.

## Truth boundary

- Do not display private reasoning or label templates as model thinking. Show a
  concise decision summary and the evidence that supports it.
- Search results are candidates, not compatibility claims.
- A resolved branch or tag is not a binding until the fixed commit is approved.
- Static analysis never implies third-party code was executed.
- No OCI/equivalent isolation means a persisted `blocked_environment`, not an
  optimistic training state.
- The universal BYOM path may end in a typed blocker. Existing registered
  Recipes retain their real data, training, evaluation, and artifact loop.
- When Agent Runtime is unavailable, the composer says `本地流程模式`. Requirement
  choices, official source search, data import, approvals, real training and
  evidence remain available; unrestricted free dialogue is not implied.

## R4-R5 acceptance snapshot

The interaction implementation is accepted only when all of the following are
observed on the current tree, not inferred from source code:

- a vague `语音模型` request produces one output question with ASR/TTS/classification
  choices and no engineering form;
- the home starter `把普通话录音转成文字` resolves to ASR and never to OCR;
- official Hugging Face/GitHub search records both empty and populated results,
  and an empty result is not presented as a provider failure;
- advanced editing reads the backend family catalog and preserves ASR while
  exposing all currently registered family definitions;
- at 390 x 844 the workspace is a modal sheet, background surfaces are inert,
  Tab and Shift+Tab stay inside, Escape closes it, and focus returns to the
  opener;
- desktop and mobile document width equal their viewport width;
- real image classification and tabular regression runs finish with deep
  verification, metric gates, ten traceable artifacts each, and a fail-closed
  pre-contract negative case.

Current run evidence lives under `runs/acceptance/r5-real-scenarios/`; local
browser screenshots live under the Git-ignored `output/frontend-audit/`. These
snapshots are implementation/verification evidence, not source artifacts, a
GitHub release or a public acceptance decision.

## First-release interaction gates

- No duplicated top progress strip, fixed five-step wizard, or permanently open
  inspector.
- The next required human action is visible inside the thread without hunting
  through tabs.
- Switching tasks clears draft-only source, entrypoint, and environment inputs.
- Search candidates, selections, bindings, plans, approvals, probes, runs, and
  reports survive refresh and server restart.
- Desktop and 390 px layouts have no horizontal overflow; the composer remains
  reachable and the workspace can be opened and closed with keyboard controls.
- All tool/progress rows are backed by persisted API facts or live agent/run
  events. There is no timer-driven fake progress.
- A failed network or Agent request remains visible with its exact operation,
  error/trace identifier and explicit retry; draft recovery is independently
  tested and retry resumes that operation instead of adding synthetic dialogue.
