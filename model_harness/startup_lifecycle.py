"""Graceful local launcher supervision and single-writer handoff.

A closed HTTP listener is not evidence that the previous writer has completed
shutdown. Probe the actual flock without removing, truncating or bypassing it.
"""
from __future__ import annotations

import errno
import math
import os
import signal
import stat
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:
    import fcntl
except ImportError:  # The POSIX launcher is unavailable, unrelated CLI commands still import.
    fcntl = None  # type: ignore[assignment]

WRITER_LEASE_FILENAME = ".specialist-model-studio.writer.lock"
DEFAULT_WRITER_WAIT_SECONDS = 60.0


def writer_wait_seconds(environment: Mapping[str, str] | None = None) -> float:
    selected = (environment if environment is not None else os.environ).get("MODEL_HARNESS_WRITER_WAIT_SECONDS", str(DEFAULT_WRITER_WAIT_SECONDS))
    try:
        value = float(selected)
    except (TypeError, ValueError):
        raise RuntimeError("MODEL_HARNESS_WRITER_WAIT_SECONDS must be a number between 0 and 600") from None
    if not math.isfinite(value) or not 0 <= value <= 600:
        raise RuntimeError("MODEL_HARNESS_WRITER_WAIT_SECONDS must be a number between 0 and 600")
    return value


def wait_for_writer_release(runs_dir: str | Path, *, timeout_seconds: float = DEFAULT_WRITER_WAIT_SECONDS,
                            on_wait: Callable[[], None] | None = None) -> float:
    """Wait for the existing writer's OS lease; never stop another process.

    This is a startup handoff gate, not the backend's lease. The server still
    acquires and holds its own lease atomically. Concurrent new starts therefore
    retain the server's existing fail-closed single-writer protection.
    """
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or not 0 <= timeout_seconds <= 600:
        raise RuntimeError("writer wait timeout must be between 0 and 600 seconds")
    if fcntl is None:
        raise RuntimeError("this launcher requires OS writer-lease support")
    path = Path(runs_dir).expanduser().resolve() / WRITER_LEASE_FILENAME
    started = time.monotonic()
    if path.is_symlink():
        raise RuntimeError("writer lease path is a symbolic link; refusing startup")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return 0.0
    announced = False
    try:
        original = os.fstat(descriptor)
        if not stat.S_ISREG(original.st_mode):
            raise RuntimeError("writer lease is not a regular lock file; refusing startup")
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
                if not announced and on_wait is not None:
                    on_wait()
                    announced = True
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise RuntimeError("previous backend still holds the runs workspace writer lease; wait for its graceful shutdown or choose a different runs directory") from None
                time.sleep(min(.1, remaining))
                continue
            try:
                current = path.stat(follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
                    raise RuntimeError("writer lease identity changed while waiting; refusing startup")
                return time.monotonic() - started
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def run_owned_launcher(argv: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> int:
    """Forward a stop to our launcher and wait for its owned-child cleanup.

    A separate session prevents Ctrl-C from reaching backend children both
    directly and through the launcher's trap. No PID lookup or broad kill is
    used. Subsequent signals do not repeatedly interrupt graceful cleanup.
    """
    process: subprocess.Popen[Any] | None = None
    received: int | None = None
    previous: dict[int, Any] = {}

    def request_stop(signum: int, _frame: Any = None) -> None:
        nonlocal received
        if received is not None:
            return
        received = signum
        if process is not None and process.poll() is None:
            try:
                process.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass

    try:
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.getsignal(signum)
                signal.signal(signum, request_stop)
        if received is not None:
            return 128 + received
        process = subprocess.Popen(list(argv), cwd=cwd, env=dict(env), start_new_session=True)
        if received is not None and process.poll() is None:
            process.send_signal(signal.SIGTERM)
        try:
            status = process.wait()
        except KeyboardInterrupt:
            request_stop(signal.SIGINT)
            status = process.wait()
        return 128 + received if received is not None else (128 - status if status < 0 else status)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
