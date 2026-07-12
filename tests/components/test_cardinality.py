from random import Random
import unittest

from protocol_model.semantics import CardinalityObligation
from protocol_model.domains import BitVectorDomain, EnumDomain, EventSpace
from protocol_model.core import CanonicalEvent, Verdict


class CardinalityObligationTests(unittest.TestCase):
    def setUp(self):
        begin = EventSpace("BEGIN", BitVectorDomain(2), {"count": BitVectorDomain(3)})
        beat = EventSpace(
            "BEAT",
            BitVectorDomain(2),
            {"data": BitVectorDomain(8), "last": EnumDomain((False, True))},
        )
        self.monitor = CardinalityObligation(
            "beats", begin, beat, lambda event: event.payload["count"] + 1
        )

    def test_exact_count_and_final_marker_complete_the_token(self):
        events = (
            CanonicalEvent("BEGIN", 2, {"count": 2}),
            CanonicalEvent("BEAT", 2, {"data": 10, "last": False}),
            CanonicalEvent("BEAT", 2, {"data": 11, "last": False}),
            CanonicalEvent("BEAT", 2, {"data": 12, "last": True}),
        )
        self.assertEqual(self.monitor.run(events).verdict, Verdict.PASS)

    def test_early_final_marker_is_rejected(self):
        events = (
            CanonicalEvent("BEGIN", 2, {"count": 1}),
            CanonicalEvent("BEAT", 2, {"data": 10, "last": True}),
        )
        result = self.monitor.run(events)
        self.assertEqual(result.verdict, Verdict.FAIL)
        self.assertEqual(result.violations[0].rule, "beats.final_marker")

    def test_different_keys_can_interleave_and_same_key_uses_oldest_token(self):
        rng = Random(5)
        state = self.monitor.initial_state()
        begins = (
            CanonicalEvent("BEGIN", 1, {"count": 1}),
            CanonicalEvent("BEGIN", 2, {"count": 0}),
        )
        for event in begins:
            state = self.monitor.step(state, event).state
        generated = []
        while state.pending:
            event = self.monitor.sample_legal(state, rng, allow_begin=False)
            generated.append(event)
            state = self.monitor.step(state, event).state
        result = self.monitor.run(begins + tuple(generated))
        self.assertEqual(result.verdict, Verdict.PASS)


if __name__ == "__main__":
    unittest.main()
