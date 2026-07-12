import unittest

from protocol_model.cli import _read_transaction, _waveform
from protocol_model.evidence import format_cardinality_run, format_ready_valid_run


class TextEvidenceTests(unittest.TestCase):
    def test_legal_waveform_shows_lowered_transfer_and_pass(self):
        samples, result = _waveform("AW", "none", 7)
        rendered = format_ready_valid_run(samples, result)
        self.assertIn("STALL", rendered)
        self.assertIn("AW_TRANSFER", rendered)
        self.assertIn("verdict=PASS", rendered)

    def test_mutated_waveform_names_the_failing_rule(self):
        samples, result = _waveform("AW", "payload", 7)
        rendered = format_ready_valid_run(samples, result)
        self.assertIn("AW.ready_valid.payload_stability", rendered)
        self.assertIn("verdict=FAIL", rendered)

    def test_read_transaction_shows_obligation_countdown(self):
        events, result, monitor = _read_transaction("none", 7)
        rendered = format_cardinality_run(
            events, result, begin_kind=monitor.begin.kind, beat_kind=monitor.beat.kind
        )
        self.assertIn("remaining=4/4", rendered)
        self.assertIn("remaining=1/4", rendered)
        self.assertIn("verdict=PASS", rendered)

    def test_early_rlast_names_cardinality_rule(self):
        events, result, monitor = _read_transaction("early-last", 7)
        rendered = format_cardinality_run(
            events, result, begin_kind=monitor.begin.kind, beat_kind=monitor.beat.kind
        )
        self.assertIn("axi4.read_beats.final_marker", rendered)
        self.assertIn("verdict=FAIL", rendered)


if __name__ == "__main__":
    unittest.main()
