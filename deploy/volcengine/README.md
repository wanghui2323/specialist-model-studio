# Volcengine private preview deployment

This directory packages the current source RC as a **private, reversible preview**
at `https://studio.learnbuddy.top`.  It does not change the product boundary in
`AGENTS.md`: this RC is not a multi-tenant or production-hardened service.

The deployment keeps both application listeners private:

- Specialist Model Studio backend: `127.0.0.1:3010`
- repository-locked DSH runtime: `127.0.0.1:3011`
- Nginx: TLS on `443`, with an explicit reviewer-IP allowlist or Basic Auth

Only Nginx is exposed.  Do not open ports `3010` or `3011` in the Volcengine
security group.

Keep long-lived conversation SSE connections in their own `limit_conn` zone.
Do not apply that connection budget to ordinary initialization APIs: a browser
may legitimately keep several event streams open while loading `/runtime`,
`/tasks`, and task projections. Rate and connection rejections use HTTP `429`,
not `503`, so they are never confused with an unavailable application backend.

For the first interaction review, keep Nginx and DNS out of the path entirely:
run the service on the ECS loopback interface and forward it over SSH:

```bash
ssh -N -L 8890:127.0.0.1:3010 itutor
```

Then open `http://127.0.0.1:8890/app`.  This is the preferred single-reviewer
gate because it preserves the repository's trusted-interface boundary.  Move
to the authenticated HTTPS route only after the conversation flow is accepted.

## Server contract

The scripts use the existing SSH alias `itutor` and these fixed paths:

```text
/opt/specialist-model-studio/releases/<UTC timestamp>-<commit>
/opt/specialist-model-studio/current -> active release
/opt/specialist-model-studio/previous -> prior release
/opt/specialist-model-studio-data/    # runs, DSH state, caches, exports
/etc/specialist-model-studio/studio.env
/etc/systemd/system/specialist-model-studio.service
/etc/nginx/conf.d/specialist-model-studio.conf
```

During the one-time migration from the legacy
`/opt/specialist-model-studio-releases/<release>` layout, the deploy and rollback
transactions accept a canonical direct child of either release root. An
unrecognized `current` target is rejected before service switching. The legacy
release remains the rollback target until the first new-layout release passes
the complete readiness gate.

Recommended preview host: Linux x86_64, 4 vCPU, 8 GiB RAM, 40 GiB free disk,
`git`, `curl`, `nginx`, `systemd`, Python 3.12, and `uv 0.9.21`.  Node must be the
locked installation at `/opt/node-v22.23.1/bin` and report `v22.23.1`.
Corepack must be present there; deployment activates the reviewed `pnpm 11.19.0`
required by DSH profile/plugin management.

DNS for `studio.learnbuddy.top` must already point at the ECS public address.
The security group should permit only the administration path in use plus
HTTP/HTTPS (`22`, `80`, `443`); restrict SSH to the administrator IP.

## One-time private-preview bootstrap

These steps intentionally remain manual.  The deployment scripts never copy,
generate, print, or overwrite a model-provider key, bridge token, Basic Auth
password, or TLS private key.

1. Create the root-only environment file on the server:

   ```bash
   ssh itutor
   sudo install -d -o root -g root -m 0700 /etc/specialist-model-studio
   sudo install -o root -g root -m 0600 /dev/null /etc/specialist-model-studio/studio.env
   sudoedit /etc/specialist-model-studio/studio.env
   ```

   Use `studio.env.example` as a field reference.  Put the real provider key
   and a long random `MODEL_HARNESS_AGENT_BRIDGE_TOKEN` only in the remote
   file.  Confirm its metadata without printing its contents:

   ```bash
   sudo stat -c '%U:%G %a %n' /etc/specialist-model-studio/studio.env
   # expected: root:root 600
   ```

2. Create Basic Auth credentials interactively.  Use the actual Nginx worker
   group on the host (`www-data` on Ubuntu, commonly `nginx` on other images):

   ```bash
   sudo htpasswd -c /etc/nginx/.htpasswd-specialist-model-studio preview
   sudo chown root:www-data /etc/nginx/.htpasswd-specialist-model-studio
   sudo chmod 0640 /etc/nginx/.htpasswd-specialist-model-studio
   ```

   The Nginx template uses `satisfy any`: explicitly reviewed IPs can open the
   preview without a browser-native authentication dialog, while every other
   source must pass Basic Auth. Keep the allowlist narrow and fail closed:

   ```nginx
   allow 203.0.113.10/32;
   deny all;
   ```

   Store it at `/etc/nginx/snippets/specialist-model-studio-allow.conf` and
   run `nginx -t` before reloading. Never commit a real reviewer IP.

3. Provision the certificate with the server's existing ACME process.  The
   Nginx template expects:

   ```text
   /etc/letsencrypt/live/studio.learnbuddy.top/fullchain.pem
   /etc/letsencrypt/live/studio.learnbuddy.top/privkey.pem
   ```

   Do not enable the TLS site before both files exist.  Keep certificate
   renewal owned by the existing ACME timer and verify it with a dry run.

4. Make sure `/opt/node-v22.23.1/bin/node`, Corepack, Python 3.12, and `uv 0.9.21` are installed.
   The deploy preflight fails closed when any required runtime is missing.

   A root-owned, isolated `uv` installation can be provisioned without changing
   Ubuntu's system Python packages:

   ```bash
   sudo /usr/bin/python3.12 -m venv /opt/uv-0.9.21
   sudo /opt/uv-0.9.21/bin/pip install --disable-pip-version-check uv==0.9.21
   sudo ln -sfn /opt/uv-0.9.21/bin/uv /usr/local/bin/uv
   ```

## Deploy the exact Git revision

Run from a clean tracked checkout.  Untracked datasets, credentials, run
outputs, and evidence are not transferred.  The revision must be the current
tip of the selected remote branch, which prevents deploying an unpushed or
ambiguous source state.

```bash
cd /path/to/specialist-model-studio
./deploy/volcengine/deploy.sh
```

Optional explicit revision and ref:

```bash
DEPLOY_REF=codex/v1.0-conversation-native \
  ./deploy/volcengine/deploy.sh <40-character-commit-sha>
```

The script uploads only the non-secret deployment helpers, clones the exact
Git commit into a new release directory, exports exact dependency versions and
SHA-256 hashes from `uv.lock`, installs those artifacts through the configured
regional PyPI mirror with hash enforcement, tests Nginx, switches `current`
atomically, starts the service, and runs the local readiness gate. Existing
releases are retained for rollback. A root-owned completion manifest inside the
release records the full Git SHA; readiness fails closed unless `/runtime`
reports the same clean source revision. The active and previous links, systemd
unit, readiness helper, and Nginx site are restored as one transaction when
activation fails.

The service is deliberately capped at two CPU cores and 7 GiB memory.  Change
those limits only through a reviewed `systemctl edit specialist-model-studio`
override and re-run the readiness check; do not edit the tracked unit in place
on the server.

## Acceptance

Server-side readiness (no credentials are printed):

```bash
ssh itutor 'sudo /usr/local/libexec/specialist-model-studio/readiness.sh 180'
```

Then open `https://studio.learnbuddy.top/app`, enter the preview Basic Auth
credentials, and verify all of the following:

1. the certificate is valid for `studio.learnbuddy.top`;
2. a new request produces one clear AI turn with an attached execution state;
3. `/runtime` reports the real DSH multi-agent implementation and a ready
   provider (the readiness script verifies this without displaying the JSON);
4. stopping or waiting is represented by one unambiguous state;
5. uploaded test data and run evidence survive a service restart.

For an HTTP-only smoke check that prompts for the password rather than storing
it in shell history:

```bash
curl --fail --user preview https://studio.learnbuddy.top/health
```

Service logs can contain user task text or model-provider diagnostics.  Access
them only on the server, do not paste them into public issues, and redact before
sharing:

```bash
ssh itutor 'sudo systemctl status specialist-model-studio --no-pager'
ssh itutor 'sudo journalctl -u specialist-model-studio --since "10 min ago" --no-pager'
```

## Rollback

Roll back to the `previous` symlink:

```bash
./deploy/volcengine/rollback.sh
```

Or select a retained release name after inspecting the server directory:

```bash
ssh itutor 'sudo find /opt/specialist-model-studio/releases -mindepth 1 -maxdepth 1 -type d -printf "%f\n" | sort'
./deploy/volcengine/rollback.sh 20260902T083000Z-11bda20
```

Rollback also runs the readiness gate.  If the target fails, the script restores
the release that was active before the rollback attempt.  It never deletes a
release or persistent data.

## Persistence and backup boundary

`/opt/specialist-model-studio-data` is intentionally outside every release.
Back up that directory separately and treat it as private customer/model data.
Never add it to Git.  A code rollback does not roll back task schemas or user
data; take a filesystem snapshot before any future data migration.
