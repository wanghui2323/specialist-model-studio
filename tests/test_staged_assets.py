from __future__ import annotations

import io
import math
import os
import stat
import struct
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path

from model_harness.errors import ContractError
from model_harness.staged_assets import (
    StagedAssetLimits,
    StagedAssetNotFound,
    StagedAssetRejected,
    StagedAssetStore,
)


def build_wav(
    *,
    frequency_hz: float = 440.0,
    duration_seconds: float = 0.12,
    sample_rate_hz: int = 16_000,
) -> bytes:
    frame_count = int(duration_seconds * sample_rate_hz)
    samples = bytearray()
    for index in range(frame_count):
        value = int(
            12_000
            * math.sin(2 * math.pi * frequency_hz * index / sample_rate_hz)
        )
        samples.extend(struct.pack("<h", value))
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate_hz)
        audio.writeframes(bytes(samples))
    return output.getvalue()


def build_zip(entries: list[tuple[str | zipfile.ZipInfo, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return output.getvalue()


def mark_first_member_encrypted(payload: bytes) -> bytes:
    mutated = bytearray(payload)
    local = mutated.find(b"PK\x03\x04")
    central = mutated.find(b"PK\x01\x02")
    if local < 0 or central < 0:
        raise AssertionError("test ZIP headers are missing")
    local_flags = struct.unpack_from("<H", mutated, local + 6)[0]
    central_flags = struct.unpack_from("<H", mutated, central + 8)[0]
    struct.pack_into("<H", mutated, local + 6, local_flags | 0x1)
    struct.pack_into("<H", mutated, central + 8, central_flags | 0x1)
    return bytes(mutated)


class StagedAssetStoreTests(unittest.TestCase):
    def test_real_wav_zip_is_staged_read_only_without_dataset_or_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = Path(temp_dir) / "task-1"
            store = StagedAssetStore(task_dir, "task-1")
            payload = build_zip(
                [
                    ("yes/alice_0.wav", build_wav(frequency_hz=440)),
                    ("no/bob_0.wav", build_wav(frequency_hz=660)),
                ]
            )

            asset = store.stage_audio_zip(payload, "samples.zip", spec_revision=3)

            self.assertEqual(asset["task_id"], "task-1")
            self.assertEqual(asset["spec_revision"], 3)
            self.assertEqual(asset["status"], "staged")
            self.assertEqual(asset["report"]["status"], "passed")
            self.assertEqual(asset["report"]["file_count"], 2)
            self.assertEqual(
                asset["report"]["labels_inferred_from_parent_folders"],
                ["no", "yes"],
            )
            self.assertFalse(asset["report"]["extracted"])
            archive_path = store.archive_path(asset["asset_id"])
            self.assertEqual(archive_path.read_bytes(), payload)
            self.assertEqual(archive_path.stat().st_mode & 0o222, 0)
            self.assertFalse((task_dir / "datasets").exists())
            self.assertFalse((task_dir / "runs").exists())
            self.assertEqual(
                sorted(path.name for path in archive_path.parent.iterdir()),
                ["asset.json", "source.zip"],
            )

    def test_restart_lists_and_gets_same_asset_and_repeat_upload_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = Path(temp_dir) / "task-restart"
            payload = build_zip([("wake/alice_0.wav", build_wav())])
            first_store = StagedAssetStore(task_dir, "task-restart")
            first = first_store.stage(payload, "wake.zip", 1)

            reopened = StagedAssetStore(task_dir, "task-restart")
            listed = reopened.list_assets()
            repeated = reopened.stage(payload, "wake.zip", 1)

            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0], first)
            self.assertEqual(reopened.get(first["asset_id"]), first)
            self.assertEqual(repeated["asset_id"], first["asset_id"])
            self.assertEqual(len(reopened.list()), 1)

    def test_rejected_archive_is_quarantined_without_retaining_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StagedAssetStore(Path(temp_dir) / "task-q", "task-q")
            payload = build_zip([("../escape.wav", build_wav())])

            with self.assertRaises(StagedAssetRejected) as raised:
                store.stage(payload, "unsafe.zip", 2)

            asset = raised.exception.asset
            self.assertEqual(asset["status"], "quarantined")
            self.assertEqual(asset["report"]["status"], "failed")
            self.assertFalse(asset["report"]["retained_payload"])
            self.assertIsNone(asset["archive"])
            self.assertEqual(store.get_asset(asset["asset_id"]), asset)
            asset_dir = store.assets_dir / asset["asset_id"]
            self.assertEqual([path.name for path in asset_dir.iterdir()], ["asset.json"])
            with self.assertRaises(ContractError):
                store.archive_path(asset["asset_id"])

            reopened = StagedAssetStore(Path(temp_dir) / "task-q", "task-q")
            self.assertEqual(
                [item["asset_id"] for item in reopened.list_assets(status="quarantined")],
                [asset["asset_id"]],
            )
            with self.assertRaises(StagedAssetRejected) as repeated:
                reopened.stage(payload, "unsafe.zip", 2)
            self.assertEqual(repeated.exception.asset_id, asset["asset_id"])

    def test_unsafe_paths_symlink_encryption_and_duplicates_are_rejected(self) -> None:
        wav = build_wav()
        symlink = zipfile.ZipInfo("yes/link.wav")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases = {
            "parent traversal": build_zip([("../escape.wav", wav)]),
            "absolute": build_zip([("/tmp/escape.wav", wav)]),
            "windows absolute": build_zip([("C:\\escape.wav", wav)]),
            "symlink": build_zip([(symlink, b"target.wav")]),
            "duplicate normalized": build_zip(
                [("YES/A.wav", wav), ("yes/a.wav", wav)]
            ),
            "non wav": build_zip([("yes/readme.txt", b"not audio")]),
            "damaged wav": build_zip([("yes/broken.wav", b"RIFFbroken")]),
            "encrypted": mark_first_member_encrypted(
                build_zip([("yes/a.wav", wav)])
            ),
        }

        for index, (label, payload) in enumerate(cases.items()):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                store = StagedAssetStore(Path(temp_dir) / "task", f"task-{index}")
                with self.assertRaises(StagedAssetRejected):
                    store.stage(payload, "samples.zip", 1)
                self.assertEqual(store.list_assets()[0]["status"], "quarantined")

    def test_file_count_uncompressed_size_and_compression_ratio_limits(self) -> None:
        wav = build_wav(duration_seconds=0.08)
        cases = (
            (
                StagedAssetLimits(max_files=1),
                build_zip([("a/1.wav", wav), ("b/2.wav", wav)]),
            ),
            (
                StagedAssetLimits(max_uncompressed_bytes=len(wav) - 1),
                build_zip([("a/1.wav", wav)]),
            ),
            (
                StagedAssetLimits(
                    max_file_bytes=2 * 1024 * 1024,
                    max_uncompressed_bytes=2 * 1024 * 1024,
                    max_compression_ratio=1.0,
                ),
                build_zip(
                    [
                        (
                            "a/long.wav",
                            build_wav(duration_seconds=60.0, frequency_hz=0),
                        )
                    ]
                ),
            ),
        )
        for index, (limits, payload) in enumerate(cases):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as temp_dir:
                store = StagedAssetStore(
                    Path(temp_dir) / "task",
                    f"task-{index}",
                    limits=limits,
                )
                with self.assertRaises(StagedAssetRejected):
                    store.stage(payload, "limits.zip", 1)

    def test_status_transitions_are_persisted_and_identity_fields_do_not_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = Path(temp_dir) / "task-state"
            store = StagedAssetStore(task_dir, "task-state")
            asset = store.stage(
                build_zip([("wake/a.wav", build_wav())]),
                "state.zip",
                4,
            )
            consumed = store.mark_consumed(asset["asset_id"])
            superseded = store.mark_superseded(asset["asset_id"])

            self.assertEqual(consumed["status"], "consumed")
            self.assertEqual(superseded["status"], "superseded")
            for field in ("asset_id", "task_id", "spec_revision", "sha256"):
                self.assertEqual(superseded[field], asset[field])
            reopened = StagedAssetStore(task_dir, "task-state")
            self.assertEqual(reopened.get_asset(asset["asset_id"])["status"], "superseded")
            with self.assertRaises(ContractError):
                reopened.mark_consumed(asset["asset_id"])

    def test_invalid_ids_and_source_paths_do_not_escape_task_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StagedAssetStore(Path(temp_dir) / "task", "task")
            with self.assertRaises(StagedAssetNotFound):
                store.get_asset("../outside")
            with self.assertRaises(StagedAssetRejected):
                store.stage(
                    build_zip([("a.wav", build_wav())]),
                    "../samples.zip",
                    1,
                )
            self.assertFalse((Path(temp_dir) / "samples.zip").exists())
            self.assertFalse((Path(temp_dir) / "outside").exists())


if __name__ == "__main__":
    unittest.main()
