# DeepSeek Harness Adapter

This package registers seven model-facing tools that call a local AI PM Model Harness server. It was authored against `@deepseek-ai/dsh` `0.1.0-rc.6` and keeps the Python training runtime independent from DeepSeek Harness.

## Install into the Web profile

Start the Python service first:

```bash
small-model-harness serve --host 127.0.0.1 --port 8765
```

From this repository, install the local plugin package into the DeepSeek Harness Web profile:

```bash
npm --prefix integrations/deepseek-harness install --ignore-scripts
dsh plugin --profile web add "$PWD/integrations/deepseek-harness"
dsh web --host 127.0.0.1 --port 3080
```

The first command installs peer SDKs next to the linked development package. The package declares `dsh.bundle.patch`, so a separate `--patch` argument is not needed.

The plugin defaults to `http://127.0.0.1:8765`. Override it only when the target is trusted:

```bash
MODEL_HARNESS_URL=http://127.0.0.1:8765 \
  dsh web --host 127.0.0.1 --port 3080
```

Ask the configured agent to list model-training Recipes or start the digit-classification teaching run. The model receives canonical JSON values, not text-parsed IDs. Applying a strategy requires the exact strategy id and `approval_confirmed: true` after explicit user approval.

## Boundaries

- Installing this plugin and seeing it enabled proves runtime registration; a provider-backed model call is a separate verification layer.
- The current built-in Recipe is a teaching experiment, not real OCR.
- The Python server has no authentication and must remain on a trusted local interface.
- DeepSeek Harness is a developer preview; re-test the adapter after upgrading it.

## Test

```bash
npm --prefix integrations/deepseek-harness test
npm --prefix integrations/deepseek-harness run check
```
