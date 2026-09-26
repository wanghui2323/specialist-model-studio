#!/usr/bin/env python3
"""Standalone, offline local OCI isolation evidence; never a training qualification.

Only a preloaded official Alpine RepoDigest and a local Unix socket are accepted.
The probe runs a repository-owned static shell program, never downloaded code.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


LABEL = "com.specialist-model-studio.oci-probe"
IMAGE_PATTERN = re.compile(r"(?:docker\.io/library/|library/)?alpine@sha256:[0-9a-f]{64}\Z")
ID_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
PROBE_SCRIPT = r"""
printf 'uid=%s\n' "$(id -u)"
if touch /.studio-oci-root-write 2>/tmp/root-write-error; then
  printf 'rootfs_write_denied=0\n'
else
  printf 'rootfs_write_denied=1\n'
  cat /tmp/root-write-error >&2
fi
if [ -e "$PROBE_HOST_HOME" ]; then printf 'host_home_visible=1\n'; else printf 'host_home_visible=0\n'; fi
printf 'interfaces=%s\n' "$(ls /sys/class/net | tr '\n' ',' | sed 's/,$//')"
printf 'ipv4_external_routes=%s\n' "$(awk 'NR>1 && $1!="lo" {n++} END {print n+0}' /proc/net/route)"
printf 'ipv6_external_routes=%s\n' "$(awk '$NF!="lo" {n++} END {print n+0}' /proc/net/ipv6_route)"
printf 'cap_eff=%s\n' "$(awk '/^CapEff:/ {print $2}' /proc/self/status)"
printf 'no_new_privs=%s\n' "$(awk '/^NoNewPrivs:/ {print $2}' /proc/self/status)"
touch /tmp/studio-oci-writable
printf 'tmpfs_write=1\n'
printf 'tmpfs_type=%s\n' "$(awk '$2=="/tmp" {print $3}' /proc/mounts)"
if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
  printf 'cgroup_version=2\n'
  read -r quota period < /sys/fs/cgroup/cpu.max
  memory=$(cat /sys/fs/cgroup/memory.max)
  pids=$(cat /sys/fs/cgroup/pids.max)
else
  printf 'cgroup_version=1\n'
  cpu=/sys/fs/cgroup/cpu
  if [ ! -d "$cpu" ]; then cpu=/sys/fs/cgroup/cpu,cpuacct; fi
  quota=$(cat "$cpu/cpu.cfs_quota_us")
  period=$(cat "$cpu/cpu.cfs_period_us")
  memory=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes)
  pids=$(cat /sys/fs/cgroup/pids/pids.max)
fi
printf 'cpu_quota=%s\ncpu_period=%s\nmemory_bytes=%s\npids=%s\n' "$quota" "$period" "$memory" "$pids"
""".strip()


class ProbeError(RuntimeError):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-binary", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    binary = Path(args.docker_binary)
    if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
        parser.error("--docker-binary must be an absolute executable file")
    endpoint = urlsplit(args.endpoint)
    if (endpoint.scheme != "unix" or endpoint.netloc or endpoint.query or endpoint.fragment
            or not args.endpoint.startswith("unix:///") or "%" in endpoint.path
            or not Path(endpoint.path).is_absolute() or not Path(endpoint.path).is_socket()):
        parser.error("--endpoint must identify an existing local Unix socket (unix:///absolute/path)")
    if not IMAGE_PATTERN.fullmatch(args.image):
        parser.error("--image must be an official Alpine RepoDigest: alpine@sha256:<64 lowercase hex>")
    if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
        parser.error("--output must be a new file in an existing directory; prior evidence is never overwritten")
    return args


class Docker:
    def __init__(self, binary: str, endpoint: str, config: str, report: dict):
        self.prefix = [binary, "--config", config, "-H", endpoint]
        # An allowlist, not os.environ.copy(): remote contexts, TLS, API overrides,
        # credential helpers, proxy settings and client plugins cannot be inherited.
        self.env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "DOCKER_CONFIG": config, "DOCKER_HOST": endpoint, "LC_ALL": "C"}
        self.report = report

    def run(self, *arguments: str, timeout: int = 20, allow_failure: bool = False) -> subprocess.CompletedProcess:
        command = [*self.prefix, *arguments]
        record = {"argv": command, "timeout_seconds": timeout}
        self.report["commands"].append(record)
        started = time.monotonic()
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, env=self.env, timeout=timeout,
                                    check=False)
        except subprocess.TimeoutExpired as error:
            record.update(timed_out=True, stdout=_text(error.stdout), stderr=_text(error.stderr))
            raise ProbeError(f"Docker {arguments[0]} timed out after {timeout}s") from error
        finally:
            record["duration_seconds"] = round(time.monotonic() - started, 3)
        record.update(returncode=result.returncode, stdout=result.stdout[:65536], stderr=result.stderr[:65536])
        if result.returncode and not allow_failure:
            raise ProbeError(f"Docker {' '.join(arguments[:2])} failed: {result.stderr.strip()[:1000]}")
        return result

    def inspect(self, target: str) -> dict:
        payload = json.loads(self.run("container", "inspect", target).stdout)
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise ProbeError("Container inspect did not return one exact object")
        return payload[0]


def _text(value: str | bytes | None) -> str:
    return (value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or "")[:65536]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeError(message)


def owned_container(container: dict, name: str, token: str) -> str:
    identity = container.get("Id", "")
    require(bool(ID_PATTERN.fullmatch(identity)), "Container ID is not an exact immutable ID")
    require(container.get("Name") == f"/{name}" and container.get("Config", {}).get("Labels", {}).get(LABEL) == token,
            "Container name/ownership label mismatch; refusing to start, stop or remove it")
    return identity


def validate_container(container: dict, image_id: str, name: str, token: str) -> str:
    identity = owned_container(container, name, token)
    config, host = container.get("Config", {}), container.get("HostConfig", {})
    require(container.get("Image") == image_id, "Container image differs from the inspected local image")
    required = {"NetworkMode": "none", "NanoCpus": 1_000_000_000, "Memory": 134_217_728,
                "MemorySwap": 134_217_728, "PidsLimit": 32, "ReadonlyRootfs": True,
                "Privileged": False, "CgroupnsMode": "private", "IpcMode": "private"}
    for key, expected in required.items():
        require(host.get(key) == expected, f"Container isolation mismatch: {key}")
    require(config.get("User") == "65534:65534", "Container must run as nonroot UID/GID 65534")
    require(set(host.get("CapDrop") or []) == {"ALL"} and not host.get("CapAdd"), "Capabilities were not all dropped")
    require("no-new-privileges" in (host.get("SecurityOpt") or []), "No-new-privileges is missing")
    require(host.get("Tmpfs") == {"/tmp": "rw,noexec,nosuid,nodev,size=16m,mode=1777"}, "Tmpfs options or size differ")
    require(not any(host.get(key) for key in ("Binds", "Devices", "DeviceRequests", "VolumesFrom", "PidMode", "UTSMode", "PortBindings", "PublishAllPorts")),
            "Host filesystem/process/device/network sharing was detected")
    require(all(mount.get("Type") == "tmpfs" and mount.get("Destination") == "/tmp" for mount in container.get("Mounts", [])),
            "Unexpected host or image volume mount")
    return identity


def validate_observations(stdout: str) -> dict[str, str]:
    observations = {}
    for line in stdout.splitlines():
        key, separator, value = line.partition("=")
        require(bool(separator) and key not in observations, "Malformed or duplicate probe observation")
        observations[key] = value
    expected = {"uid": "65534", "rootfs_write_denied": "1", "host_home_visible": "0", "interfaces": "lo",
                "ipv4_external_routes": "0", "ipv6_external_routes": "0", "cap_eff": "0000000000000000",
                "no_new_privs": "1", "tmpfs_write": "1", "tmpfs_type": "tmpfs", "memory_bytes": "134217728", "pids": "32"}
    for key, value in expected.items():
        require(observations.get(key) == value, f"Actual isolation negative test failed or is missing: {key}")
    require(observations.get("cgroup_version") in {"1", "2"}, "Unsupported or missing cgroup evidence")
    quota, period = int(observations.get("cpu_quota", "0")), int(observations.get("cpu_period", "0"))
    require(quota == period and period > 0, "Actual cgroup CPU quota is not exactly one CPU")
    return observations


def cleanup(docker: Docker, name: str, token: str, report: dict) -> None:
    result = docker.run("container", "inspect", name, allow_failure=True)
    if result.returncode:
        require("No such container" in result.stderr or "No such object" in result.stderr,
                "Could not establish whether the owned container exists; cleanup unverified")
        report["cleanup"] = {"status": "absent", "name": name}
        return
    payload = json.loads(result.stdout)
    require(isinstance(payload, list) and len(payload) == 1, "Ambiguous cleanup inspection")
    identity = owned_container(payload[0], name, token)
    if payload[0].get("State", {}).get("Running"):
        docker.run("container", "stop", "--time", "2", identity, timeout=10)
    stopped = docker.inspect(identity)
    owned_container(stopped, name, token)
    require(stopped.get("State", {}).get("Running") is False, "Owned container did not stop")
    report["stopped_container"] = stopped
    docker.run("container", "rm", identity)
    absent = docker.run("container", "inspect", identity, allow_failure=True)
    require(absent.returncode != 0 and ("No such container" in absent.stderr or "No such object" in absent.stderr),
            "Removal of the exact owned container was not verified")
    report["cleanup"] = {"status": "removed", "name": name, "container_id": identity}


def run_probe(args: argparse.Namespace) -> dict:
    token = uuid.uuid4().hex
    name = f"studio-oci-probe-{token}"
    report = {"schema_version": "1.0", "evidence_type": "LocalOCIProbeEvidence", "status": "failed",
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "endpoint": args.endpoint,
              "image": args.image, "probe_id": token, "container_name": name, "commands": [], "errors": [],
              "scope": "Standalone CPU-only runtime isolation probe; not ModelTrial, Run, QualificationRun, recipe approval, GPU evidence or production readiness."}
    created_attempted = False
    with tempfile.TemporaryDirectory(prefix="studio-oci-client-") as config:
        docker = Docker(args.docker_binary, args.endpoint, config, report)
        try:
            home = str(Path.home())
            require(Path(home).is_absolute() and Path(home).is_dir(), "Host HOME must be an existing absolute directory")
            report["host_home_checked"] = home
            report["server"] = json.loads(docker.run("version", "--format", "{{json .Server}}").stdout)
            require(isinstance(report["server"], dict) and bool(report["server"].get("Version")), "No Docker server identity")
            require(report["server"].get("Os") == "linux", "The Docker server must report Linux")
            server_arch = report["server"].get("Arch")
            require(isinstance(server_arch, str) and bool(server_arch), "The Docker server must report an explicit CPU architecture")
            images = json.loads(docker.run("image", "inspect", args.image).stdout)
            require(isinstance(images, list) and len(images) == 1, "Local immutable image is missing or ambiguous; never pull automatically")
            image = images[0]
            report["image_inspect"] = image
            require(image.get("Os") == "linux", "The local image must report Linux")
            require(image.get("Architecture") == server_arch, "Image and Docker server CPU architectures must match exactly; no emulation fallback")
            # Docker may canonicalize the familiar Alpine repository name.
            requested_digest = args.image.rsplit("@", 1)[1]
            require(any(IMAGE_PATTERN.fullmatch(item) and item.rsplit("@", 1)[1] == requested_digest for item in image.get("RepoDigests", [])),
                    "Image inspect does not attest the requested official Alpine RepoDigest")
            require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", image.get("Id", ""))), "Image has no immutable ID")
            require(not image.get("Config", {}).get("Volumes"), "Image-declared volumes are not allowed")
            created_attempted = True  # A timeout may still have created the named container.
            created = docker.run("container", "create", "--name", name, "--label", f"{LABEL}={token}",
                                 "--pull=never", "--cpus", "1", "--memory", "128m", "--memory-swap", "128m",
                                 "--pids-limit", "32", "--network", "none", "--user", "65534:65534", "--read-only",
                                 "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--ipc", "private",
                                 "--cgroupns", "private", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
                                 "--env", f"PROBE_HOST_HOME={home}", "--entrypoint", "/bin/sh", args.image,
                                 "-c", "exec sleep 300")
            container = docker.inspect(name)
            report["container_inspect"] = container
            identity = validate_container(container, image["Id"], name, token)
            require(created.stdout.strip() == identity, "Create response and inspected container identity differ")
            docker.run("container", "start", identity)
            running = docker.inspect(identity)
            require(owned_container(running, name, token) == identity and running.get("State", {}).get("Running") is True,
                    "Container did not enter the running state")
            report["running_container"] = running
            result = docker.run("container", "exec", identity, "/bin/sh", "-eu", "-c", PROBE_SCRIPT, timeout=20)
            report["observations"] = validate_observations(result.stdout)
            report["probe_checks_passed"] = True
        except (Exception, KeyboardInterrupt) as error:
            report["errors"].append(f"{type(error).__name__}: {error}")
        finally:
            if created_attempted:
                try:
                    cleanup(docker, name, token, report)
                except (Exception, KeyboardInterrupt) as error:
                    report["errors"].append(f"Cleanup {type(error).__name__}: {error}")
                    report["cleanup"] = {"status": "unverified", "name": name, "ownership_label": f"{LABEL}={token}"}
            else:
                report["cleanup"] = {"status": "not_created", "name": name}
    if report.get("probe_checks_passed") is True and report["cleanup"]["status"] == "removed" and not report["errors"]:
        report["status"] = "passed"
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # Reserve before Docker activity. Exclusive creation also handles a race after
    # argument validation, and failed checks cannot overwrite older success evidence.
    with args.output.open("x", encoding="utf-8") as output:
        os.chmod(args.output, 0o600)
        report = run_probe(args)
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    print(json.dumps({"status": report["status"], "evidence": str(args.output), "errors": report["errors"]}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
