from __future__ import annotations

import concurrent.futures
import io
import json
import stat
import struct
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from model_harness.errors import ContractError
from model_harness.io_utils import read_json, write_json
from model_harness.material_inspection import (
    MaterialConflict, MaterialInspectionStore, _Inspector, _digest, validate_metadata,
)
from model_harness.server import create_app


def archive(entries, compression=zipfile.ZIP_DEFLATED):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=compression) as bundle:
        for name, content in entries:
            bundle.writestr(name, content)
    return result.getvalue()


def pcm_wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 160)
    return output.getvalue()


def picture():
    output = io.BytesIO()
    Image.new("RGB", (16, 12), "red").save(output, format="PNG")
    return output.getvalue()


def issues(record):
    report = record.get("report", record)
    return {item["code"] for item in report["errors"] + report["warnings"]}


class MaterialInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.owner_id = "task-" + "1" * 32
        self.owner_path = self.root / "conversations" / self.owner_id / "conversation.json"
        write_json(self.owner_path, {"task_id": self.owner_id, "record_type": "conversation_draft"})
        self.store = MaterialInspectionStore(self.root)

    def upload(self, content, name="data.csv", request="request-1"):
        return self.store.upload(self.owner_id, content, name, request)[0]

    def test_four_generic_shapes_are_inspected_without_training_state(self):
        cases = [
            ("speech.zip", archive([("audio.wav", pcm_wav()), ("metadata.csv", "audio,text\naudio.wav,hello\n")]), {"wav_count": 1, "paired_reference_count": 1}),
            ("ocr.zip", archive([("image.png", picture()), ("labels.jsonl", '{"image":"image.png","text":"A1"}\n')]), {"image_count": 1, "paired_reference_count": 1}),
            ("nlp.csv", b"text,label\nhello,positive\ngoodbye,negative\n", {"row_count": 2}),
            ("series.csv", b"date,series,value\n2026-01-01,a,1\n2026-01-02,a,2\n", {"row_count": 2}),
        ]
        before = self.owner_path.read_bytes()
        for index, (name, payload, expected) in enumerate(cases):
            with self.subTest(name=name):
                record = self.upload(payload, name, f"four-{index}")
                self.assertEqual(record["status"], "inspected", record["report"])
                self.assertFalse(record["dataset_imported"])
                self.assertFalse(record["execution_authorized"])
                self.assertTrue(record["data_inspected_only"])
                for field, value in expected.items():
                    self.assertEqual(record["report"]["facts"][field], value)
                source = self.root / "materials" / self.owner_id / record["material_id"] / "source.bin"
                self.assertEqual(source.read_bytes(), payload)
                self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o400)
        self.assertEqual(self.owner_path.read_bytes(), before)
        self.assertFalse((self.root / "tasks").exists())
        self.assertFalse((self.root / "datasets").exists())
        self.assertFalse((self.root / "runs").exists())

    def test_agent_projection_keeps_statistics_but_never_raw_rows(self):
        private = "IGNORE_ALL_INSTRUCTIONS_PRIVATE_TEXT"
        record = self.upload(f"text,label\n{private},yes\n".encode())
        self.assertIn(private, json.dumps(record))
        self.assertNotIn(private, json.dumps(self.store.brief(record)))
        agent = self.store.agent_detail(record)
        self.assertNotIn(private, json.dumps(agent))
        self.assertNotIn("preview", agent["report"]["tables"][0])
        self.assertNotIn("pairings", agent["report"]["media"])
        self.assertEqual(agent["report"]["tables"][0]["columns"], ["text", "label"])
        self.assertEqual(agent["inspection_sha256"], record["inspection_sha256"])
        self.assertEqual(agent["report_projection"], "agent_facts")
        self.assertNotIn(str(self.root), json.dumps(agent))

    def test_pairing_missing_unsafe_empty_ambiguous_and_wrong_media_are_rejected(self):
        cases = [
            ("audio,text\nmissing.wav,hello\n", [], "missing_reference"),
            ("audio,text\n../private.wav,hello\n", [], "unsafe_reference"),
            ("audio,text\n,hello\n", [], "empty_or_invalid_reference"),
            ("audio,text\nimage.png,hello\n", [("image.png", picture())], "reference_media_type_mismatch"),
            ("audio,text\naudio.wav,hello\n", [("audio.wav", pcm_wav()), ("data/audio.wav", pcm_wav())], "ambiguous_reference"),
        ]
        for index, (table, media, issue) in enumerate(cases):
            with self.subTest(issue=issue):
                record = self.upload(archive([("data/metadata.csv", table), *media]), "paired.zip", f"pair-{index}")
                self.assertEqual(record["status"], "rejected")
                self.assertIn(issue, issues(record))
                self.assertFalse(record["file"]["retained"])
                self.assertFalse((self.root / "materials" / self.owner_id / record["material_id"] / "source.bin").exists())

    def test_same_file_with_conflicting_annotations_is_rejected(self):
        record = self.upload(archive([("audio.wav", pcm_wav()), ("metadata.csv", "audio,text\naudio.wav,hello\naudio.wav,other\n")]), "paired.zip")
        self.assertEqual(record["status"], "rejected")
        self.assertIn("conflicting_annotation", issues(record))
        self.assertEqual(record["report"]["facts"]["conflicting_annotation_count"], 1)

    def test_equivalent_csv_jsonl_references_are_warned_not_double_declared_unique(self):
        record = self.upload(archive([("image.png", picture()), ("labels.csv", "image,text\nimage.png,A1\n"), ("labels.jsonl", '{"image":"image.png","text":"A1"}\n')]), "paired.zip")
        self.assertEqual(record["status"], "inspected")
        self.assertEqual(record["report"]["facts"]["paired_reference_count"], 2)
        self.assertEqual(record["report"]["facts"]["unique_referenced_files"], 1)
        self.assertIn("references_shared_by_tables", issues(record))

    def test_relative_annotation_reference_and_standalone_unverified_reference(self):
        record = self.upload(archive([("data/audio.wav", pcm_wav()), ("data/metadata.csv", "audio,text\naudio.wav,hello\n")]), "paired.zip")
        self.assertEqual(record["status"], "inspected")
        standalone = self.upload(b"audio,text\naudio.wav,hello\n", request="standalone")
        self.assertEqual(standalone["status"], "inspected")
        self.assertEqual(standalone["report"]["facts"]["paired_reference_count"], 0)
        self.assertIn("external_pairing_unverified", issues(standalone))

    def test_unsafe_archive_paths_and_case_collisions_are_rejected(self):
        cases = [[(name, b"a")] for name in ["../outside.txt", "/absolute.txt", "C:\\host\\file.txt", "x/../x.txt", "bad\nfile.txt"]]
        cases += [[("a", b"file"), ("a/b.txt", b"other")], [("A.txt", b"one"), ("a.txt", b"two")], [("é.txt", b"one"), ("e\u0301.txt", b"two")]]
        for index, entries in enumerate(cases):
            with self.subTest(entries=entries):
                record = self.upload(archive(entries), "unsafe.zip", f"unsafe-{index}")
                self.assertEqual(record["status"], "rejected")
                self.assertIn("unsafe_or_invalid_archive", issues(record))
        nul_name = archive([("a.txt", b"content")]).replace(b"a.txt", b"a\0txt")
        record = self.upload(nul_name, "nul.zip", "nul-path")
        self.assertEqual(record["status"], "rejected")
        self.assertFalse((self.root / "outside.txt").exists())

    def test_links_special_files_and_encrypted_archives_are_rejected(self):
        for index, kind in enumerate([stat.S_IFLNK, stat.S_IFIFO]):
            entry = zipfile.ZipInfo("linked.txt")
            entry.create_system = 3
            entry.external_attr = (kind | 0o777) << 16
            record = self.upload(archive([(entry, b"target")]), "unsafe.zip", f"link-{index}")
            self.assertEqual(record["status"], "rejected")
        payload = bytearray(archive([("a.txt", b"content")]))
        local = payload.index(b"PK\x03\x04")
        central = payload.index(b"PK\x01\x02")
        struct.pack_into("<H", payload, local + 6, struct.unpack_from("<H", payload, local + 6)[0] | 1)
        struct.pack_into("<H", payload, central + 8, struct.unpack_from("<H", payload, central + 8)[0] | 1)
        self.assertEqual(self.upload(bytes(payload), "encrypted.zip")["status"], "rejected")

    def test_archive_entry_size_total_ratio_and_count_budgets(self):
        cases = [
            ("MAX_MATERIAL_BYTES", 5, archive([("x.txt", b"123456")], zipfile.ZIP_STORED)),
            ("MAX_UNCOMPRESSED_BYTES", 7, archive([("a.txt", b"1234"), ("b.txt", b"5678")])),
            ("MAX_COMPRESSION_RATIO", 2, archive([("x.txt", b"x" * 4096)])),
            ("MAX_ENTRIES", 1, archive([("a.txt", b"a"), ("b.txt", b"b")])),
        ]
        for constant, limit, payload in cases:
            with self.subTest(constant=constant), patch(f"model_harness.material_inspection.{constant}", limit):
                report = _Inspector().inspect(payload, "bounded.zip")
                self.assertIn("unsafe_or_invalid_archive", issues(report))
                self.assertEqual(report["facts"]["files_inspected"], 0)

    def test_corrupt_archives_and_media_report_errors_without_crashing(self):
        cases = [("bad.zip", b"PK-not-a-zip"), ("image.png", b"not-image"), ("audio.wav", pcm_wav()[:-3]), ("table.csv", b"x,y\n\xff,b\n"), ("table.jsonl", b'{"x":NaN}\n'), ("duplicate.jsonl", b'{"x":1,"x":2}\n')]
        for index, (filename, payload) in enumerate(cases):
            with self.subTest(filename=filename):
                self.assertEqual(self.upload(payload, filename, f"corrupt-{index}")["status"], "rejected")
        import zlib
        with patch("model_harness.material_inspection._read_member", side_effect=zlib.error("malformed deflate")):
            record = self.upload(archive([("file.txt", b"hello")]), "bad-deflate.zip", "deflate")
        self.assertEqual(record["status"], "rejected")

    def test_no_nested_extraction_or_execution_for_unknown_content(self):
        payload = archive([("nested.zip", archive([("script.py", b"raise AssertionError('do not execute')")])), ("script.py", b"raise AssertionError('do not execute')")])
        record = self.upload(payload, "opaque.zip")
        self.assertEqual(record["status"], "inspected")
        self.assertIn("content_not_decoded", issues(record))
        self.assertEqual(record["report"]["facts"]["files_inspected"], 2)
        self.assertFalse(any(path.name == "script.py" for path in self.root.rglob("*")))

    def test_empty_ragged_duplicate_header_and_excessive_tables_are_rejected(self):
        cases = [b"x,y\n", b"x,y\n1,2,3\n", b"x,x\n1,2\n", b"x, x\n1,2\n", b"x,y\n1\n"]
        for index, content in enumerate(cases):
            with self.subTest(content=content):
                self.assertEqual(self.upload(content, request=f"table-{index}")["status"], "rejected")
        for constant, limit, content in [("MAX_COLUMNS", 1, b"a,b\n"), ("MAX_ROWS", 1, b"a\n1\n2\n"), ("MAX_CELLS", 1, b"a,b\n1,2\n")]:
            with self.subTest(constant=constant), patch(f"model_harness.material_inspection.{constant}", limit):
                self.assertEqual(self.upload(content, request=constant)["status"], "rejected")

    def test_csv_whitespace_missing_and_duplicate_counts_preserve_source(self):
        payload = b" text , label \nhello,yes\nhello,yes\n,\n"
        record = self.upload(payload)
        self.assertEqual(record["status"], "inspected")
        table = record["report"]["tables"][0]
        self.assertEqual(table["columns"], ["text", "label"])
        self.assertEqual(table["missing_counts"], {"text": 1, "label": 1})
        self.assertEqual(table["duplicate_row_count"], 1)
        self.assertIn("header_whitespace", issues(record))

    def test_column_profiles_are_useful_statistics_without_raw_values(self):
        payload = b"text,label,value,date\nprivate-alpha,A,1,2024-01-01\nprivate-beta,B,3.5,2024-01-03\nprivate-alpha,A,,2024-01-03\n, ,bad,invalid\n"
        record = self.upload(payload)
        table = record["report"]["tables"][0]
        profiles = table["column_profiles"]
        self.assertEqual(profiles["text"]["non_empty_count"], 3)
        self.assertEqual(profiles["text"]["distinct_count"], 2)
        self.assertEqual(profiles["label"]["distinct_count"], 2)
        self.assertEqual(profiles["text"]["text_length"], {"count": 3, "min": 12, "max": 13, "unit": "unicode_codepoints"})
        self.assertEqual(profiles["value"]["numeric"], {"count": 2, "min": 1.0, "max": 3.5})
        dates = profiles["date"]["iso_date"]
        self.assertEqual(dates["count"], 3)
        self.assertEqual(dates["distinct_count"], 2)
        self.assertEqual(dates["min"], "2024-01-01")
        self.assertEqual(dates["max"], "2024-01-03")
        self.assertEqual(dates["missing_calendar_days"], 1)
        self.assertEqual(dates["gap_count"], 1)
        self.assertEqual(dates["max_gap_days"], 1)
        safe = json.dumps(self.store.agent_detail(record))
        self.assertNotIn("private-alpha", safe)
        self.assertNotIn("private-beta", safe)
        self.assertIn("not_semantic_accuracy_or_training_sufficiency", safe)

    def test_grouped_dates_report_duplicates_gaps_and_anonymous_groups(self):
        payload = b"entity,date,value\nsecret-east,2024-01-01,1\nsecret-east,2024-01-03,2\nsecret-east,2024-01-03,3\nsecret-west,2024-01-01,4\nsecret-west,2024-01-02,5\n"
        record = self.upload(payload)
        table = record["report"]["tables"][0]
        profile = next(item for item in table["grouped_date_profiles"] if item["group_column"] == "entity")
        self.assertEqual(profile["group_count"], 2)
        self.assertEqual(profile["analyzed_row_count"], 5)
        self.assertEqual(profile["duplicate_pair_count"], 1)
        self.assertFalse(profile["pair_unique"])
        self.assertEqual([group["row_count"] for group in profile["groups"]], [3, 2])
        self.assertEqual(profile["groups"][0]["date_coverage"]["missing_calendar_days"], 1)
        self.assertEqual(profile["groups"][1]["date_coverage"]["missing_calendar_days"], 0)
        self.assertNotIn("secret-east", json.dumps(self.store.agent_detail(record)))
        self.assertFalse(profile["group_values_disclosed"])

    def test_profile_limits_are_explicit_and_do_not_invent_exact_uniqueness(self):
        payload = b"entity,date\na,2024-01-01\na,2024-01-02\nb,2024-01-03\nb,2024-01-04\n"
        with patch("model_harness.material_inspection.MAX_PROFILE_DISTINCT", 2), patch("model_harness.material_inspection.MAX_GROUP_DATE_PAIRS", 2):
            record = self.upload(payload)
        table = record["report"]["tables"][0]
        dates = table["column_profiles"]["date"]
        self.assertEqual(dates["distinct_count"], 2)
        self.assertTrue(dates["distinct_count_is_lower_bound"])
        self.assertTrue(dates["iso_date"]["distinct_count_is_lower_bound"])
        self.assertIsNone(dates["iso_date"]["missing_calendar_days"])
        pair = table["grouped_date_profiles"][0]
        self.assertIsNone(pair["pair_unique"])
        self.assertTrue(pair["duplicate_pair_count_is_lower_bound"])
        self.assertTrue(pair["groups"][1]["date_coverage"]["distinct_count_is_lower_bound"])

    def test_new_profiles_do_not_rewrite_previous_inspection_receipts(self):
        payload = b"text,label\nprivate,yes\n"
        record = self.upload(payload)
        for table in record["report"]["tables"]:
            for key in list(table):
                if "profile" in key:
                    del table[key]
        record.pop("inspection_sha256")
        record["inspection_sha256"] = _digest(record)
        stored = self.root / "materials" / self.owner_id / record["material_id"] / "inspection.json"
        write_json(stored, record)
        before = stored.read_bytes()
        replay, replayed = self.store.upload(self.owner_id, payload, "data.csv", "request-1")
        self.assertTrue(replayed)
        self.assertEqual(replay, record)
        self.assertNotIn("column_profiles", self.store.agent_detail(record)["report"]["tables"][0])
        self.assertEqual(stored.read_bytes(), before)

    def test_large_profile_reports_are_bounded_and_mark_reductions(self):
        columns = ["entity", "date", *[f"column_{index}" for index in range(22)]]
        content = ",".join(columns) + "\n" + "".join(
            ",".join([f"group-{index}", f"2024-01-{index + 1:02d}", *[str(index % (column + 2)) for column in range(22)]]) + "\n" for index in range(28))
        record = self.upload(archive([(f"table-{index}.csv", content) for index in range(10)]), "large-profiles.zip")
        self.assertEqual(record["status"], "inspected")
        self.assertLessEqual(len(json.dumps(record["report"], ensure_ascii=False).encode()), 64 * 1024)
        self.assertTrue(record["report"]["facts"]["preview_truncated"])
        self.assertEqual(record["report"]["facts"]["table_count"], 10)

    def test_compact_agent_projection_does_not_claim_semantic_checks_or_false_group_gaps(self):
        payload = b"entity,date,label\nprivate-a,2024-01-01,yes\nprivate-a,2024-01-01,no\nprivate-b,2024-01-02,yes\n"
        record = self.upload(payload)
        original = json.dumps(record, ensure_ascii=False, sort_keys=True)
        agent = self.store.agent_detail(record)
        self.assertEqual(agent["report"]["media_pairing"], "not_applicable")
        self.assertNotIn("conflicting_annotation_count", agent["report"]["facts"])
        self.assertIn("annotation_semantics", agent["report"]["not_checked"])
        self.assertIn("derived_field_semantic_consistency", agent["report"]["not_checked"])
        self.assertIn("model_quality", agent["report"]["not_checked"])
        grouped = next(item for item in agent["report"]["tables"][0]["grouped_date_profiles"] if item["group_column"] == "entity")
        self.assertFalse(grouped["pair_unique"])
        self.assertNotIn("groups", grouped)
        self.assertEqual(json.dumps(record, ensure_ascii=False, sort_keys=True), original)
        self.assertNotIn("private-a", json.dumps(agent))

    def test_pixel_budgets_are_checked_before_image_decode(self):
        with patch("model_harness.material_inspection.MAX_IMAGE_PIXELS", 100):
            record = self.upload(picture(), "small.png")
        self.assertEqual(record["status"], "rejected")
        self.assertEqual(record["report"]["facts"]["image_count"], 0)

    def test_payload_and_header_validation(self):
        for payload in [b"", b"a" * 5]:
            with patch("model_harness.material_inspection.MAX_MATERIAL_BYTES", 4), self.assertRaises(ContractError):
                self.upload(payload)
        for filename in ["", "../a.csv", "/private/a.csv", "C:\\a.csv", "a\0.csv", "a\n.csv", "a" * 181]:
            with self.subTest(filename=filename), self.assertRaises(ContractError):
                validate_metadata(filename, "valid")
        for request in ["", "../a", "a/next", "x" * 161]:
            with self.subTest(request=request), self.assertRaises(ContractError):
                validate_metadata("data.csv", request)

    def test_receipt_idempotency_replay_restart_and_conflicts(self):
        payload = b"a,b\n1,2\n"
        record, replay = self.store.upload(self.owner_id, payload, "data.csv", "same")
        self.assertFalse(replay)
        reopened = MaterialInspectionStore(self.root)
        repeated, replay = reopened.upload(self.owner_id, payload, "data.csv", "same")
        self.assertTrue(replay)
        self.assertEqual(repeated, record)
        self.assertEqual(reopened.receipt(self.owner_id, "same"), record)
        self.assertEqual(len(reopened.list(self.owner_id)), 1)
        for changed_payload, changed_name in [(b"a,b\n3,4\n", "data.csv"), (payload, "renamed.csv")]:
            with self.assertRaises(MaterialConflict):
                reopened.upload(self.owner_id, changed_payload, changed_name, "same")

    def test_concurrent_replay_commits_one_receipt(self):
        stores = [MaterialInspectionStore(self.root), MaterialInspectionStore(self.root)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda store: store.upload(self.owner_id, b"a,b\n1,2\n", "data.csv", "concurrent"), stores))
        self.assertEqual(sorted(replayed for _, replayed in results), [False, True])
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(len(self.store.list(self.owner_id)), 1)

    def test_owner_isolation_archival_and_symlink_boundaries(self):
        record = self.upload(b"a,b\n1,2\n")
        with self.assertRaises(FileNotFoundError):
            self.store.get("task-other", record["material_id"])
        with self.assertRaises(FileNotFoundError):
            self.store.upload("../escape", b"a", "data.csv", "req")
        other_id = "task-" + "2" * 32
        write_json(self.root / "tasks" / other_id / "task.json", {"task_id": other_id})
        with self.assertRaises(FileNotFoundError):
            self.store.get(other_id, record["material_id"])
        write_json(self.owner_path, {"task_id": self.owner_id, "archived_at_utc": "2026-10-04"})
        self.assertEqual(self.store.get(self.owner_id, record["material_id"]), record)
        with self.assertRaises(MaterialConflict):
            self.upload(b"a,b\n1,2\n", request="archived")
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / "materials" / other_id).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(MaterialConflict):
            self.store.upload(other_id, b"a,b\n1,2\n", "data.csv", "req")
        self.assertEqual(list(outside.iterdir()), [])

    def test_tampered_receipts_and_malformed_owner_fail_closed(self):
        record = self.upload(b"a,b\n1,2\n")
        path = self.root / "materials" / self.owner_id / record["material_id"] / "inspection.json"
        altered = dict(record, dataset_imported=True)
        write_json(path, altered)
        with self.assertRaises(MaterialConflict):
            self.store.receipt(self.owner_id, "request-1")
        for invalid in ["[1]", "broken-json"]:
            path.write_text(invalid)
            with self.assertRaises(MaterialConflict):
                self.store.get(self.owner_id, record["material_id"])
        self.owner_path.write_text("broken-json")
        with self.assertRaises(MaterialConflict):
            self.store.owner(self.owner_id)


class MaterialInspectionServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.app = create_app(Path(self.temporary.name) / "runs")
        self.runtime = self.app.state.conversation_runtime
        self.workspace = self.app.state.training_workspace
        self.start_patch = patch.object(self.runtime, "start")
        self.stop_patch = patch.object(self.runtime, "stop")
        self.start_patch.start()
        self.stop_patch.start()
        self.addCleanup(self.start_patch.stop)
        self.addCleanup(self.stop_patch.stop)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        response = self.client.post("/conversations", json={"create_request_id": "materials-http", "title": "材料检查"})
        self.assertEqual(response.status_code, 201, response.text)
        self.owner_id = response.json()["conversation"]["conversation_id"]
        self.base = f"/conversations/{self.owner_id}"

    def upload(self, content=b"text,label\nprivate-sample,positive\n", filename="data.csv", request="upload-1", scope=None):
        return self.client.post(f"{scope or self.base}/materials", content=content, headers={"X-Filename": filename, "X-Request-ID": request, "Content-Type": "application/octet-stream"})

    def test_upload_list_detail_receipt_context_and_promotion_preserve_one_owner(self):
        with (
            patch.object(self.workspace, "create_task", side_effect=AssertionError("no task creation")),
            patch.object(self.app.state.run_service, "submit", side_effect=AssertionError("no Run")),
        ):
            response = self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        record = response.json()["material"]
        material_id = record["material_id"]
        self.assertEqual(record["owner_type_at_inspection"], "conversation")
        self.assertEqual(self.client.get(f"{self.base}/materials/{material_id}").json()["material"], record)
        self.assertEqual(self.client.get(f"{self.base}/material-requests/upload-1").json()["material"], record)
        listed = self.client.get(f"{self.base}/materials").json()
        self.assertEqual(listed["count"], 1)
        self.assertTrue(listed["materials"][0]["detail_available"])
        self.assertNotIn("private-sample", json.dumps(listed))
        agent = self.client.get(f"{self.base}/materials/{material_id}?view=agent")
        self.assertEqual(agent.status_code, 200)
        self.assertNotIn("private-sample", agent.text)
        before = self.client.get(self.base).json()
        self.assertIsNone(before["task"])
        self.assertEqual(before["material_inspections"]["count"], 1)
        context = self.client.get(f"{self.base}/agent-context")
        self.assertEqual(context.status_code, 200, context.text)
        self.assertFalse(context.json()["owner"]["training_task_exists"])
        self.assertEqual(context.json()["data"]["material_inspections"]["status"], "observed")
        self.assertNotIn("private-sample", context.text)
        self.assertEqual(self.client.get("/tasks").json()["tasks"], [])
        task, _ = self.workspace.promote_conversation(self.owner_id, request_id="promote", name="自有模型", business_goal="检查资料后确定方案")
        self.assertIsNone(task.get("recipe_id"))
        after = self.client.get(self.base).json()
        self.assertEqual(after["task"]["task_id"], self.owner_id)
        self.assertEqual(after["task"]["material_inspections"]["count"], 1)
        self.assertEqual(self.client.get(f"/tasks/{self.owner_id}/materials/{material_id}").json()["material"], record)
        replay = self.upload(scope=f"/tasks/{self.owner_id}")
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertTrue(replay.json()["replayed"])
        self.assertEqual(self.client.get(f"/tasks/{self.owner_id}").json()["task"]["material_inspections"]["count"], 1)
        self.assertEqual(self.client.get(f"{self.base}/material-requests/upload-1").json()["material"], record)

    def test_http_metadata_owner_caps_rejection_and_conflict_statuses(self):
        self.assertEqual(self.client.post(f"{self.base}/materials", content=b"a").status_code, 422)
        self.assertEqual(self.upload(content=b"").status_code, 422)
        self.assertEqual(self.upload(filename="%2Fprivate%2Fa.csv").status_code, 422)
        oversized = self.client.post(f"{self.base}/materials", content=b"tiny", headers={"X-Filename": "data.csv", "X-Request-ID": "oversize", "Content-Length": str(25 * 1024 * 1024 + 1)})
        self.assertEqual(oversized.status_code, 413)
        with patch("model_harness.server.MAX_MATERIAL_BYTES", 4):
            self.assertEqual(self.upload(content=b"12345", request="over-stream").status_code, 413)
        self.assertEqual(self.upload(scope="/conversations/task-absent").status_code, 404)
        initial = self.upload()
        self.assertEqual(initial.status_code, 201)
        self.assertEqual(self.upload(content=b"text,label\ndifferent,value\n").status_code, 409)
        rejected = self.upload(content=b"broken", filename="bad.zip", request="bad")
        self.assertEqual(rejected.status_code, 201)
        self.assertEqual(rejected.json()["material"]["status"], "rejected")
        self.assertEqual(self.client.get(f"{self.base}/material-requests/bad").json()["material"]["status"], "rejected")
        self.assertEqual(self.client.get(f"{self.base}/material-requests/missing").status_code, 404)
        self.workspace.promote_conversation(self.owner_id, request_id="promote", name="目标", business_goal="具体目标")
        self.workspace.archive_task(self.owner_id)
        self.assertEqual(self.upload(request="after-archive").status_code, 409)
        self.assertEqual(self.client.get(f"{self.base}/materials").status_code, 200)

    def test_corrupt_inspection_is_409_in_owner_summary_and_list(self):
        record = self.upload().json()["material"]
        path = self.workspace.root / "materials" / self.owner_id / record["material_id"] / "inspection.json"
        path.write_text("invalid")
        self.assertEqual(self.client.get(self.base).status_code, 409)
        self.assertEqual(self.client.get(f"{self.base}/materials").status_code, 409)
        self.workspace.promote_conversation(self.owner_id, request_id="promote", name="目标", business_goal="具体目标")
        self.assertEqual(self.client.get(f"/tasks/{self.owner_id}").status_code, 409)

    def promote_regression(self):
        task, _ = self.workspace.promote_conversation(self.owner_id, request_id="promote-regression", name="质量预测", business_goal="根据温度预测产品质量数值", capability_request={"modality": "tabular", "objective": "regression", "target_kind": "numeric", "target_column": "quality"})
        self.assertEqual(task["recipe_id"], "tabular-regression")
        self.assertEqual(task["capability_decision"]["status"], "resolved")
        return task

    def regression_material(self, request="regression-material"):
        payload = "sample_id,temperature,quality\n" + "".join(f"sample-{i},{18 + i * .25},{7.2 + i * .1}\n" for i in range(40))
        response = self.upload(payload.encode(), "measurements.csv", request)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["material"]

    def bridge(self, material, request="material-import-1", options=None, client=None):
        return (client or self.client).post(f"/tasks/{self.owner_id}/dataset-from-material", json={"material_id": material["material_id"], "inspection_sha256": material["inspection_sha256"], "request_id": request, "options": options if options is not None else {"target_column": "quality", "ignored_columns": ["sample_id"], "delimiter": ","}})

    def test_material_csv_bridge_persists_replays_and_preserves_training_confirmation(self):
        material = self.regression_material()
        self.promote_regression()
        with patch.object(self.app.state.run_service, "submit", side_effect=AssertionError("must not start Run")):
            initial = self.bridge(material)
        self.assertEqual(initial.status_code, 201, initial.text)
        result = initial.json()
        dataset_id = result["task"]["dataset_id"]
        self.assertTrue(dataset_id)
        self.assertEqual(result["dataset_upload"]["dataset_id"], dataset_id)
        self.assertEqual(result["dataset_upload"]["payload_sha256"], material["file"]["sha256"])
        self.assertFalse(result["task"]["contract_confirmed"])
        self.assertEqual(result["task"]["run_ids"], [])
        self.assertFalse(result["idempotent_replay"])
        replay = self.bridge(material)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertTrue(replay.json()["idempotent_replay"])
        self.assertEqual(replay.json()["task"]["dataset_history"], [dataset_id])
        fresh_app = create_app(Path(self.temporary.name) / "runs")
        fresh_client = TestClient(fresh_app)
        self.addCleanup(fresh_client.close)
        fresh_replay = self.bridge(material, client=fresh_client)
        self.assertEqual(fresh_replay.status_code, 201, fresh_replay.text)
        self.assertEqual(fresh_replay.json()["task"]["dataset_id"], dataset_id)
        self.assertTrue(fresh_replay.json()["idempotent_replay"])
        retained = fresh_client.get(f"{self.base}/materials/{material['material_id']}").json()["material"]
        self.assertEqual(retained, material)
        self.assertFalse(retained["dataset_imported"])
        conflict = self.bridge(material, options={"target_column": "temperature", "ignored_columns": ["sample_id"]})
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(self.workspace.get_task(self.owner_id)["dataset_history"], [dataset_id])

    def test_material_image_zip_bridge_reuses_existing_adapter_without_starting_run(self):
        entries = []
        for label, color in [("red", (210, 20, 20)), ("blue", (20, 20, 210))]:
            for index in range(8):
                image = Image.new("RGB", (20, 20), color)
                image.putpixel((index, index), (index, 255, 0))
                output = io.BytesIO()
                image.save(output, format="PNG")
                entries.append((f"{label}/{index}.png", output.getvalue()))
        material = self.upload(archive(entries), "classes.zip").json()["material"]
        task, _ = self.workspace.promote_conversation(self.owner_id, request_id="image-promotion", name="颜色分类", business_goal="将图片分为红色蓝色两个类别", capability_request={"modality": "image", "objective": "classification", "target_kind": "class_label"})
        self.assertEqual(task["recipe_id"], "image-folder-classification")
        response = self.bridge(material, options={})
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()["task"]
        self.assertEqual(task["data_adapter_id"], "image-folder-zip")
        self.assertEqual(task["dataset_report"]["total_images"], 16)
        self.assertFalse(task["contract_confirmed"])
        self.assertEqual(task["run_ids"], [])

    def test_material_bridge_requires_bound_resolved_verified_and_unarchived_task(self):
        material = self.regression_material()
        self.assertEqual(self.bridge(material).status_code, 404)
        task, _ = self.workspace.promote_conversation(self.owner_id, request_id="unresolved-promotion", name="专用语音模型", business_goal="文字生成语音", capability_request={"modality": "audio", "objective": "tts", "target_kind": "waveform"})
        self.assertIsNone(task["recipe_id"])
        self.assertEqual(self.bridge(material).status_code, 409)
        self.assertIsNone(self.workspace.get_task(self.owner_id).get("dataset_id"))
        self.workspace.archive_task(self.owner_id)
        self.assertEqual(self.bridge(material).status_code, 409)
        self.assertFalse(any(self.workspace.root.glob("tasks/*/datasets/*")))

    def test_material_bridge_rejects_foreign_digest_and_source_tampering(self):
        material = self.regression_material()
        self.promote_regression()
        wrong_digest = dict(material, inspection_sha256="0" * 64)
        self.assertEqual(self.bridge(wrong_digest).status_code, 409)
        other = self.workspace.create_task("other", "检查不同文件")
        foreign, _ = self.app.state.material_inspections.upload(other["task_id"], b"a,b\n1,2\n", "other.csv", "foreign")
        self.assertEqual(self.bridge(foreign).status_code, 404)
        for index, mode in enumerate(["changed", "truncated", "missing", "symlink"]):
            record = self.regression_material(request=f"tamper-{index}")
            source = self.workspace.root / "materials" / self.owner_id / record["material_id"] / "source.bin"
            payload = source.read_bytes()
            source.chmod(0o600)
            if mode == "changed":
                source.write_bytes(b"X" + payload[1:])
            elif mode == "truncated":
                source.write_bytes(payload[:-1])
            else:
                source.unlink()
                if mode == "symlink":
                    outside = Path(self.temporary.name) / "outside.csv"
                    outside.write_bytes(payload)
                    source.symlink_to(outside)
            with self.subTest(mode=mode):
                response = self.bridge(record, request=f"import-tamper-{index}")
                self.assertEqual(response.status_code, 409, response.text)
                self.assertNotIn(str(self.temporary.name), response.text)
        self.assertIsNone(self.workspace.get_task(self.owner_id).get("dataset_id"))

    def test_material_bridge_rejects_unaccepted_material_and_arbitrary_options(self):
        self.promote_regression()
        rejected = self.upload(b"bad", "broken.zip", "rejected").json()["material"]
        self.assertEqual(self.bridge(rejected).status_code, 409)
        material = self.regression_material()
        for options in [{"execute": True}, {"ignored_columns": "sample_id"}, {"delimiter": "::"}, {"target_column": None}]:
            with self.subTest(options=options):
                self.assertEqual(self.bridge(material, options=options).status_code, 422)
        self.assertEqual(self.bridge(material, options={"data_adapter": "image-folder-zip"}).status_code, 422)
        response = self.client.post(f"/tasks/{self.owner_id}/dataset-from-material", json={"material_id": material["material_id"], "inspection_sha256": material["inspection_sha256"], "request_id": "path-injection", "source_path": "/private/file.csv"})
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(self.workspace.get_task(self.owner_id).get("dataset_id"))

    def test_material_bridge_rejects_stale_spec_inside_import_lock(self):
        material = self.regression_material()
        task = self.promote_regression()
        body = {"material_id": material["material_id"], "inspection_sha256": material["inspection_sha256"], "request_id": "spec-bound-import", "options": {"target_column": "quality", "ignored_columns": ["sample_id"]}, "base_spec_revision": task["current_spec_revision"] + 1}
        response = self.client.post(f"/tasks/{self.owner_id}/dataset-from-material", json=body)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIsNone(self.workspace.get_task(self.owner_id).get("dataset_id"))
        body["base_spec_revision"] = True
        self.assertEqual(self.client.post(f"/tasks/{self.owner_id}/dataset-from-material", json=body).status_code, 422)
        body["base_spec_revision"] = task["current_spec_revision"]
        response = self.client.post(f"/tasks/{self.owner_id}/dataset-from-material", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertFalse(response.json()["task"]["contract_confirmed"])
        replay = self.client.post(f"/tasks/{self.owner_id}/dataset-from-material", json=body)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertTrue(replay.json()["idempotent_replay"])
        self.assertEqual(replay.json()["task"]["dataset_id"], response.json()["task"]["dataset_id"])
        # Even if a later TaskSpec advances, exact receipt reconciliation must
        # not create a second Dataset or make a lost success impossible to read.
        body["base_spec_revision"] = task["current_spec_revision"] + 99
        replay = self.client.post(f"/tasks/{self.owner_id}/dataset-from-material", json=body)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertTrue(replay.json()["idempotent_replay"])

    def test_material_csv_schema_is_persistent_complete_and_path_free(self):
        columns = [f"column_{index}" for index in range(32)]
        payload = (";".join(columns) + "\n" + ";".join(str(index) for index in range(32)) + "\n").encode()
        material = self.upload(payload, "wide.csv").json()["material"]
        self.assertTrue(material["report"]["tables"][0]["columns_truncated"])
        schema = self.client.get(f"{self.base}/materials/{material['material_id']}/csv-schema")
        self.assertEqual(schema.status_code, 200, schema.text)
        self.assertEqual(schema.json()["columns"], columns)
        self.assertEqual(schema.json()["delimiter"], ";")
        self.assertEqual(schema.json()["inspection_sha256"], material["inspection_sha256"])
        self.assertNotIn("preview", schema.json())
        self.assertNotIn(str(self.temporary.name), schema.text)
        self.assertFalse(schema.json()["dataset_imported"])
        non_csv = self.upload(picture(), "picture.png", "picture").json()["material"]
        self.assertEqual(self.client.get(f"{self.base}/materials/{non_csv['material_id']}/csv-schema").status_code, 422)

    def test_real_four_scene_fixtures_via_http_when_locally_available(self):
        fixtures = Path(__file__).resolve().parents[1] / "runs/acceptance/20261004-four-scenarios"
        cases = [
            ("speech/tts_speech_review.zip", {"wav_count": 40, "missing_reference_count": 0}),
            ("ocr/ocr-single-line.zip", {"image_count": 320, "missing_reference_count": 0}),
            ("nlp/data/train.csv", {"row_count": 72}),
            ("timeseries/data/train.csv", {"row_count": 1095}),
        ]
        if not all((fixtures / relative).is_file() for relative, _ in cases):
            self.skipTest("local generated acceptance fixtures are not source artifacts")
        for index, (relative, expected) in enumerate(cases):
            with self.subTest(file=relative):
                path = fixtures / relative
                response = self.upload(path.read_bytes(), path.name, f"real-{index}")
                self.assertEqual(response.status_code, 201, response.text)
                record = response.json()["material"]
                self.assertEqual(record["status"], "inspected", record["report"])
                for key, count in expected.items():
                    self.assertEqual(record["report"]["facts"][key], count)
                self.assertFalse(record["dataset_imported"])
                self.assertFalse(record["execution_authorized"])
                agent = self.app.state.material_inspections.agent_detail(record)
                self.assertLess(len(json.dumps(agent, ensure_ascii=False, indent=2)), 12_000)
                self.assertEqual(len(agent["report"]["tables"]), len(record["report"]["tables"]))
                original_tables = {table["file"]: table for table in record["report"]["tables"]}
                for table in agent["report"]["tables"]:
                    self.assertEqual(table["row_count"], original_tables[table["file"]]["row_count"])
                    self.assertEqual(table["columns"], original_tables[table["file"]]["columns"])
                    self.assertTrue(all(0 <= profile["non_empty_count"] <= table["row_count"] for profile in table.get("column_profiles", {}).values()))
                if relative == "ocr/ocr-single-line.zip":
                    self.assertEqual({table["file"]: table["row_count"] for table in agent["report"]["tables"]}, {"challenge/annotations.jsonl": 40, "test/annotations.jsonl": 60, "train/annotations.jsonl": 180, "validation/annotations.jsonl": 40})
                if relative == "nlp/data/train.csv":
                    profiles = record["report"]["tables"][0]["column_profiles"]
                    self.assertEqual(profiles["label"]["distinct_count"], 6)
                    self.assertEqual(profiles["text"]["non_empty_count"], 72)
                if relative == "timeseries/data/train.csv":
                    table = record["report"]["tables"][0]
                    self.assertEqual(table["column_profiles"]["store_id"]["distinct_count"], 3)
                    self.assertEqual(table["column_profiles"]["date"]["iso_date"]["distinct_count"], 365)
                    pair = next(item for item in table["grouped_date_profiles"] if item["group_column"] == "store_id" and item["date_column"] == "date")
                    self.assertEqual(pair["group_count"], 3)
                    self.assertTrue(pair["pair_unique"])
                    self.assertEqual([group["row_count"] for group in pair["groups"]], [365, 365, 365])
                    self.assertTrue(all(group["date_coverage"]["missing_calendar_days"] == 0 for group in pair["groups"]))
        self.assertEqual(self.client.get("/tasks").json()["tasks"], [])
        self.assertEqual(self.client.get(f"{self.base}/materials").json()["count"], 4)
        self.assertFalse(any(self.workspace.root.glob("tasks/*/datasets/*")))


if __name__ == "__main__":
    unittest.main()
