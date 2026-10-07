# Immutable multi-platform Python 3.12 base. Package installation uses only
# hash-locked wheels from the declared public indexes; no user data or models.
ARG BASE_IMAGE=python:3.12.15-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f
FROM ${BASE_IMAGE}
ARG LOCKFILE=requirements-linux-arm64.lock
COPY ${LOCKFILE} /tmp/worker-requirements.lock
COPY wheels/ /tmp/wheels/
RUN python -m pip install --no-cache-dir --no-index --find-links=/tmp/wheels --require-hashes --only-binary=:all: -r /tmp/worker-requirements.lock \
    && rm /tmp/worker-requirements.lock && rm -rf /tmp/wheels
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
USER 65532:65532
WORKDIR /workspace/output
CMD ["python", "--version"]
