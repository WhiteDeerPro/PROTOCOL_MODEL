from random import Random
import unittest

from protocol_model.patterns import ClockedReadyValid, ReadyValidSample
from protocol_model.domains import BitVectorDomain, EventSpace
from protocol_model.core import CanonicalEvent, Verdict


class ClockedReadyValidTests(unittest.TestCase):
    def setUp(self):
        self.space = EventSpace(
            "TRANSFER", BitVectorDomain(2), {"data": BitVectorDomain(8)}
        )
        self.monitor = ClockedReadyValid("data", self.space, clock="clk")
        self.event = CanonicalEvent("TRANSFER", 1, {"data": 42})

    def test_transfer_occurs_exactly_on_valid_and_ready(self):
        samples = (
            ReadyValidSample(0, False, True, clock="clk"),
            ReadyValidSample(1, True, False, self.event, "clk"),
            ReadyValidSample(2, True, True, self.event, "clk"),
        )
        result = self.monitor.run(samples)
        self.assertEqual(result.verdict, Verdict.PASS)
        self.assertEqual(len(result.emissions), 1)
        self.assertEqual(result.emissions[0].payload["data"], 42)
        self.assertEqual(result.emissions[0].timestamp, 2)

    def test_withdrawing_valid_while_stalled_is_a_safety_violation(self):
        result = self.monitor.run(
            (
                ReadyValidSample(0, True, False, self.event, "clk"),
                ReadyValidSample(1, False, True, clock="clk"),
            )
        )
        self.assertEqual(result.verdict, Verdict.FAIL)
        self.assertEqual(result.violations[0].rule, "data.valid_stability")

    def test_changing_payload_while_stalled_is_a_safety_violation(self):
        changed = CanonicalEvent("TRANSFER", 1, {"data": 43})
        result = self.monitor.run(
            (
                ReadyValidSample(0, True, False, self.event, "clk"),
                ReadyValidSample(1, True, True, changed, "clk"),
            )
        )
        self.assertEqual(result.verdict, Verdict.FAIL)
        self.assertEqual(result.violations[0].rule, "data.payload_stability")

    def test_stalled_finite_prefix_is_inconclusive_not_failed_liveness(self):
        result = self.monitor.run(
            (ReadyValidSample(0, True, False, self.event, "clk"),)
        )
        self.assertEqual(result.verdict, Verdict.INCONCLUSIVE)
        self.assertFalse(result.violations)

    def test_event_space_is_checked_before_transfer(self):
        malformed = CanonicalEvent("TRANSFER", 1, {"data": 999})
        result = self.monitor.run(
            (ReadyValidSample(0, True, True, malformed, "clk"),)
        )
        self.assertEqual(result.verdict, Verdict.FAIL)
        self.assertEqual(result.violations[0].rule, "data.event_space")

    def test_legal_generator_and_monitor_share_one_automaton(self):
        rng = Random(19)
        state = self.monitor.initial_state()
        samples = []
        for cycle in range(200):
            sample = self.monitor.sample_legal(state, rng, cycle)
            transition = self.monitor.step(state, sample)
            self.assertIsNone(transition.fault)
            state = transition.state
            samples.append(sample)
        result = self.monitor.run(samples)
        self.assertNotEqual(result.verdict, Verdict.FAIL)


if __name__ == "__main__":
    unittest.main()
