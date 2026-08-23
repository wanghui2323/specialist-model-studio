# AI PM Model Harness Boundaries

This project is an educational, agent-operated harness for auditable specialist-model training.

- Keep the default experience delegation-first: the agent advances independently and pauses only for missing data, authorization, immutable acceptance criteria, unsafe execution, or release approval.
- Preserve an optional learning view from the same run. Do not build a separate tutorial workflow that diverges from execution evidence.
- Treat `task_contract.json` release gates and test-set policy as human-owned. Agents may report failure but must not weaken gates or reuse the final test set for model selection.
- Keep source code, small public examples, schemas, and validation logic in the repository. Keep private user data, credentials, generated voice, customer documents, large datasets, downloaded weights, and run outputs outside version control.
- `runs/`, `.venv/`, model caches, and downloaded datasets are reproducible local state, not source artifacts.
- v0.7 Beta has three real user-data vertical slices: image-folder classification, CSV tabular regression, and class-folder WAV keyword classification after a trusted declarative RecipeFactory registration. The built-in digits Recipe remains teaching-only. These slices stay supported unchanged in v0.9.
- v0.9 adds Universal BYOM: an arbitrary public Hugging Face or GitHub training repository may enter the `discover → analyze → plan → resource check → isolated build → qualification → register → train` protocol. Support means the repository reaches one of two honest terminal states: a real trained model, or a typed `BlockerEvidence` explaining why this machine cannot train it. It does not promise every repository will train successfully.
- Third-party repository code, install scripts, and human-authored repair patches may only execute inside an OCI container or a worker with equivalent file, process, network and resource isolation. A plain host subprocess is never an acceptable execution backend. Without a verified isolation runtime the system must analyze only and record `blocked_environment`.
- A dynamic RecipeVersion may only be registered after a real QualificationRun passes all declared checks and a human approves that exact evidence digest. Agents may propose new BuildAttempts but must never generate repair patches autonomously, overwrite prior evidence, lower a human gate, or widen execution permissions.
- v0.9 executes CPU-only inside the isolation boundary. ResourceProbe still detects MPS/CUDA/VRAM, but ResourceFitReport must mark accelerators as detected-but-unusable-in-v0.9 and say why. Never claim GPU acceleration because the host has a GPU.
- Keep OCR detection/recognition, ASR, TTS/voice cloning, object detection, segmentation, forecasting, cloud/GPU orchestration, and production deployment explicitly unsupported until each has a tested Recipe, Data Adapter, evidence path, and product loop.
- Treat a training task as the owner of its dataset versions, confirmed task contract and run lineage. Replacing data or changing gates must invalidate prior confirmation and must not present an older run as the current result.
- Dataset archives must be inspected for path traversal, file-count/size limits, decoding failures, class count, minimum samples, duplicate leakage and cross-label conflicts before training.
- Local tests and browser loops prove a local feasibility workflow, not production readiness, shadow testing or publication to GitHub.
