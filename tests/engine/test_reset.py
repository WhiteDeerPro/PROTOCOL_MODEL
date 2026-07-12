import unittest

from protocol_model.patterns import ClockedReadyValid, ReadyValidSample, ResetEpoch, ResetSample
from protocol_model.domains import BitVectorDomain, EventSpace
from protocol_model.core import CanonicalEvent, Verdict


class ResetEpochTests(unittest.TestCase):
    def setUp(self):
        space = EventSpace("TRANSFER", BitVectorDomain(2), {"data": BitVectorDomain(8)})
        ready_valid = ClockedReadyValid("data", space, clock="clk")
        self.monitor = ResetEpoch(
            "data_reset",
            ready_valid,
            inactive=lambda sample: not sample.valid,
            inactive_reason="VALID must be low during reset",
        )
        self.first = CanonicalEvent("TRANSFER", 1, {"data": 10})
        self.second = CanonicalEvent("TRANSFER", 1, {"data": 20})

    def test_reset_clears_a_stalled_inner_automaton(self):
        result = self.monitor.run(
            (
                ResetSample(False, ReadyValidSample(0, True, False, self.first, "clk")),
                ResetSample(True, ReadyValidSample(1, False, False, clock="clk")),
                ResetSample(False, ReadyValidSample(2, True, True, self.second, "clk")),
            )
        )
        self.assertEqual(result.verdict, Verdict.PASS)
        self.assertEqual([event.payload["data"] for event in result.emissions], [20])
        self.assertEqual(result.final_state.epoch, 1)

    def test_valid_high_during_reset_is_rejected(self):
        result = self.monitor.run(
            (
                ResetSample(True, ReadyValidSample(0, True, True, self.first, "clk")),
            )
        )
        self.assertEqual(result.verdict, Verdict.FAIL)
        self.assertEqual(result.violations[0].rule, "data_reset.reset_inactive")


if __name__ == "__main__":
    unittest.main()
