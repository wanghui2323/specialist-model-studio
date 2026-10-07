import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts/acceptance/agent_acceptance.py"
spec = importlib.util.spec_from_file_location("agent_acceptance", MODULE)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class AgentAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case = {"id":"case-unknown-domain", "checks":[{"id":"send", "kind":"page_action", "action":"send"}], "reviews":[{"id":"meaning", "criterion":"Preserve the user goal"}]}

    def capture(self, text="Read-only advice; no training has run", action_status="completed"):
        (self.root / "page.txt").write_text(text)
        (self.root / "page.png").write_bytes(b"screenshot-fixture-not-real-page-proof")
        self.row = {"id":"obs-1", "case_id":self.case["id"], "url":"http://localhost/app?conversation=owned", "action":{"kind":"send"}, "action_status":action_status,
                    "snapshot":{"path":"page.txt", "sha256":acceptance.digest(self.root/"page.txt")}, "screenshot":{"path":"page.png", "sha256":acceptance.digest(self.root/"page.png")}}
        (self.root / "journal.jsonl").write_text(json.dumps(self.row)+"\n")

    def review(self, role="independent_agent", verdict="passed", quote="no training has run", sha=None):
        row = {"criterion_id":"meaning", "reviewer_id":"reviewer-separate-session", "reviewer_role":role, "verdict":verdict, "rationale":"The reply accurately identifies preparation as distinct from execution", "evidence":[{"observation_id":"obs-1", "quote":quote, "snapshot_sha256":sha or self.row["snapshot"]["sha256"]}]}
        (self.root/"reviews.json").write_text(json.dumps({"reviews":[row]}))

    def test_missing_page_observation_never_passes(self):
        result = acceptance.evaluate(self.case, self.root)
        self.assertEqual(result["verdict"], "incomplete")
        self.assertEqual(result["criteria"][0]["status"], "incomplete")

    def test_browser_action_without_semantic_review_is_incomplete(self):
        self.capture()
        result = acceptance.evaluate(self.case, self.root)
        self.assertEqual(result["criteria"][0]["status"], "passed")
        self.assertEqual(result["verdict"], "incomplete")

    def test_executor_self_scoring_fabricated_quote_or_stale_sha_cannot_pass(self):
        for kwargs in ({"role":"executor"}, {"quote":"I invented this quote"}, {"sha":"0"*64}):
            self.capture(); self.review(**kwargs)
            self.assertEqual(acceptance.evaluate(self.case,self.root)["verdict"], "incomplete")

    def test_independent_negative_review_overrides_successful_action(self):
        self.capture(); self.review(verdict="failed")
        self.assertEqual(acceptance.evaluate(self.case,self.root)["verdict"], "failed")

    def test_matching_evidence_and_review_can_pass_arbitrary_domain(self):
        self.capture(); self.review()
        self.assertEqual(acceptance.evaluate(self.case,self.root)["verdict"], "passed")

    def test_altered_evidence_cross_case_and_duplicate_identity_fail(self):
        self.capture(); self.review()
        (self.root/"page.txt").write_text("altered")
        self.assertEqual(acceptance.evaluate(self.case,self.root)["verdict"], "failed")
        self.capture(); self.row["case_id"]="foreign"
        (self.root/"journal.jsonl").write_text(json.dumps(self.row)+"\n")
        self.assertEqual(acceptance.evaluate(self.case,self.root)["verdict"], "failed")
        self.capture()
        with (self.root/"journal.jsonl").open("a") as stream: stream.write(json.dumps(self.row)+"\n")
        self.assertEqual(acceptance.evaluate(self.case,self.root)["verdict"], "failed")

    def test_absolute_parent_and_symlink_references_are_rejected(self):
        for path in ("/etc/passwd", "../foreign.json"):
            with self.assertRaises(ValueError): acceptance.confined(self.root,path)
        with tempfile.TemporaryDirectory() as outside:
            (self.root/"link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError): acceptance.confined(self.root,"link/out.json")

    def test_execution_pass_does_not_override_quality_fail(self):
        self.capture(); self.review()
        fact = self.root/"run.json"
        fact.write_text(json.dumps({"status":"completed","quality_passed":False}))
        (self.root/"facts.json").write_text(json.dumps({"sources":[{"id":"run", "path":"run.json", "sha256":acceptance.digest(fact)}]}))
        self.case["checks"] += [{"id":"run", "kind":"fact", "source":"run", "field":"status", "equals":"completed"}, {"id":"quality", "kind":"fact", "source":"run", "field":"quality_passed", "equals":True}]
        self.assertEqual(acceptance.evaluate(self.case,self.root)["verdict"], "failed")

    def test_unknown_checker_and_empty_case_are_not_vacuous_success(self):
        for case in ({"id":"empty"}, {"id":"unknown","checks":[{"id":"x","kind":"guess"}]}):
            with self.assertRaises(ValueError): acceptance.evaluate(case,self.root)


if __name__ == "__main__": unittest.main()
