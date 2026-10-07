from copy import deepcopy
import unittest

from model_harness.projection_history import ProjectionHistoryReader


def entry(seq, kind="assistant/message", **data):
    return {"event": {"seq": seq, "type": kind, "data": data}}


class ProjectionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.events = [entry(1, "turn/start"), entry(2, "user/message", text="goal"), entry(3, "assistant/chunk", text="token"), entry(4, text="answer")]
        self.requests = []

        def call(method, request):
            self.assertEqual(method, "session.history")
            self.requests.append(deepcopy(request))
            rows = [row for row in self.events if row["event"]["seq"] < request.get("beforeSeq", 10**9)]
            if request["maxMessages"] == 1:
                return {"events": deepcopy(rows[-3:]), "hasMore": len(rows) > 3}
            return {"events": deepcopy(rows), "hasMore": False}
        self.reader = ProjectionHistoryReader(call, frozenset({"user/message", "assistant/message", "tool/result", "turn/end"}))

    def test_unchanged_and_appended_history_reads_tail_but_preserves_turns_and_tool_receipts(self):
        first = self.reader.read("owner")
        self.assertEqual([row["event"]["seq"] for row in first["events"]], [1, 2, 4])
        self.assertEqual(self.reader.read("owner"), first)
        self.events += [entry(5, "tool/result", receipt={"task": "owner"}), entry(6, "turn/end")]
        new = self.reader.read("owner")
        self.assertEqual([row["event"]["seq"] for row in new["events"]], [1, 2, 4, 5, 6])
        self.assertEqual([r["maxMessages"] for r in self.requests], [240, 1, 1])

    def test_changed_anchor_discards_old_prefix_and_rereads_complete_history(self):
        self.reader.read("owner")
        self.events[3] = entry(4, text="changed")
        found = self.reader.read("owner")
        self.assertEqual(found["events"][-1]["event"]["data"]["text"], "changed")
        self.assertEqual([r["maxMessages"] for r in self.requests], [240, 1, 240])

    def test_reset_and_other_owner_never_reuse_an_old_prefix(self):
        self.reader.read("owner")
        self.events = [entry(1, "user/message", text="reset")]
        found = self.reader.read("owner")
        self.assertEqual(len(found["events"]), 1)
        self.reader.read("other")
        self.assertEqual(self.requests[-1]["maxMessages"], 240)

    def test_failure_is_not_replaced_with_cached_facts(self):
        self.reader.read("owner")
        self.reader.call = lambda *_: (_ for _ in ()).throw(ValueError("provider unavailable"))
        with self.assertRaisesRegex(ValueError, "provider unavailable"):
            self.reader.read("owner")

    def test_anchor_may_be_a_chunk_without_discarding_a_later_continuation_relay(self):
        self.events.append(entry(5, "assistant/chunk", text="last-token"))
        self.reader.read("owner")
        self.events += [entry(6, "user/message", source={"kind": "coordinator", "senderSessionId": "root"}), entry(7, "turn/start")]
        found = self.reader.read("owner")
        self.assertEqual([r["event"]["seq"] for r in found["events"]], [1, 2, 4, 6, 7])


if __name__ == "__main__":
    unittest.main()
