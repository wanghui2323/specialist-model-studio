# DeepSeek Harness Adapter

This package registers 15 model-facing tools that call a local AI PM Model Harness server. It was authored against the `dsh` `0.1.0-rc.6` CLI and `@deepseek-ai/dsh-tools` `0.1.0-rc.8`, while keeping the Python training runtime independent from DeepSeek Harness.

## Install into the Web profile

Start the Python service first:

```bash
small-model-harness serve --host 127.0.0.1 --port 8765
```

From this repository, install the local plugin package into the DeepSeek Harness Web profile:

```bash
npm --prefix integrations/deepseek-harness install --ignore-scripts
./scripts/install_dsh_preset.sh
dsh plugin --profile web add "$PWD/integrations/deepseek-harness"
dsh web --host 127.0.0.1 --port 3080
```

The first command installs peer SDKs next to the linked development package. The package declares `dsh.bundle.patch`, so a separate `--patch` argument is not needed.

The preset installer writes the repository-managed `model-training` preset to the DSH user preset directory. It refuses to overwrite a preset without this project's management marker. The bundle selects that preset for new sessions, so the UI shows “模型训练模式” and the model does not receive general shell or file-editing tools.

An existing DSH user setting takes precedence over the bundle default. If a previously configured profile still opens in “标准模式”, choose “模型训练模式” under Settings → Agent Preset; this affects only new sessions and preserves existing session history.

The plugin defaults to `http://127.0.0.1:8765`. Override it only when the target is trusted:

```bash
MODEL_HARNESS_URL=http://127.0.0.1:8765 \
  dsh web --host 127.0.0.1 --port 3080
```

Ask the configured agent to create or inspect a training task. It can then import a user-approved local ZIP, configure and confirm the contract, start a real task run, read results and apply an approved optimization strategy. The model receives canonical JSON values, not text-parsed IDs.

Mutating training tools pass through DeepSeek Harness native approval. The Python backend independently enforces dataset, confirmation, state and lineage requirements; approval in the conversation host does not replace those checks.

After one-time installation, start both services with:

```bash
./scripts/start_conversation_harness.sh
```

Open `http://127.0.0.1:3080` for the primary conversation. Tool results return a task-specific `workbench_url`; that page is an evidence view for the same backend task, not a second state store.

## Boundaries

- Installing this plugin and seeing it enabled proves runtime registration; a provider-backed model call is a separate verification layer.
- The user-data Recipe currently performs multiclass image classification; it is not real OCR, object detection, speech training or a production vision platform.
- The Python server has no authentication and must remain on a trusted local interface.
- DeepSeek Harness is a developer preview; re-test the adapter after upgrading it.

## Test

```bash
npm --prefix integrations/deepseek-harness test
npm --prefix integrations/deepseek-harness run check
```
