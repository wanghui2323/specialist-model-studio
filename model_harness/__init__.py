"""Specialist Model Studio training engine."""

import os


# ONNX Runtime's non-Windows telemetry uploader has caused process-shutdown races
# on macOS. Keep local model work private and stable unless an operator explicitly
# opts telemetry back in before importing this package.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

__version__ = "0.9.0rc1"
