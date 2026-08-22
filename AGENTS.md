# AI PM Model Harness Boundaries

This project is an educational, agent-operated harness for auditable specialist-model training.

- Keep the default experience delegation-first: the agent advances independently and pauses only for missing data, authorization, immutable acceptance criteria, unsafe execution, or release approval.
- Preserve an optional learning view from the same run. Do not build a separate tutorial workflow that diverges from execution evidence.
- Treat `task_contract.json` release gates and test-set policy as human-owned. Agents may report failure but must not weaken gates or reuse the final test set for model selection.
- Keep source code, small public examples, schemas, and validation logic in the repository. Keep private user data, credentials, generated voice, customer documents, large datasets, downloaded weights, and run outputs outside version control.
- `runs/`, `.venv/`, model caches, and downloaded datasets are reproducible local state, not source artifacts.
- v0.7 Beta has three real user-data vertical slices: image-folder classification, CSV tabular regression, and class-folder WAV keyword classification after a trusted declarative RecipeFactory registration. The built-in digits Recipe remains teaching-only.
- Hugging Face integration is limited to official discovery/model-card inspection, an explicitly approved immutable commit, verified local ModelAsset files, and CPU ONNX image features for the image-classification slice. Do not imply arbitrary Hub model fine-tuning or deployment support.
- Keep OCR detection/recognition, ASR, TTS/voice cloning, object detection, segmentation, forecasting, text/NLP training, arbitrary generated Python Recipes, cloud/GPU orchestration, and production deployment explicitly unsupported until each has a tested Recipe, Data Adapter, evidence path, and product loop.
- Treat a training task as the owner of its dataset versions, confirmed task contract and run lineage. Replacing data or changing gates must invalidate prior confirmation and must not present an older run as the current result.
- Dataset archives must be inspected for path traversal, file-count/size limits, decoding failures, class count, minimum samples, duplicate leakage and cross-label conflicts before training.
- Local tests and browser loops prove a local feasibility workflow, not production readiness, shadow testing or publication to GitHub.
