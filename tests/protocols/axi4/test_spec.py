from random import Random
import unittest

from protocol_model.core import CanonicalEvent, Verdict
from protocol_model.patterns import ClockedReadyValid, ReadyValidSample, ResetEpoch, ResetSample
from protocol_model.protocols.axi4 import Axi4Config, build_axi4_spec


class Axi4SpecTests(unittest.TestCase):
    def setUp(self):
        self.spec = build_axi4_spec(Axi4Config(address_width=32, data_width=64, id_width=4))

    def test_elaboration_builds_five_typed_directional_channels(self):
        self.assertEqual(set(self.spec.channels), {"AW", "W", "B", "AR", "R"})
        self.assertEqual(self.spec.channel("AW").source_role, "manager")
        self.assertEqual(self.spec.channel("R").source_role, "subordinate")
        self.assertEqual(self.spec.parameters["data_width"], 64)

    def test_large_symbolic_aw_space_samples_without_enumeration(self):
        aw = self.spec.channel("AW").transfer
        rng = Random(11)
        events = [aw.sample(rng) for _ in range(200)]
        self.assertTrue(all(aw.contains(event) for event in events))
        self.assertTrue(any(int(event.payload["addr"]) > 1_000_000 for event in events))

    def test_crossing_4kb_burst_is_rejected(self):
        aw = self.spec.channel("AW").transfer
        event = CanonicalEvent(
            "AW_TRANSFER",
            0,
            {
                "addr": 0xFF0,
                "len": 4,
                "size": 3,
                "burst": "INCR",
                "lock": 0,
                "cache": 0,
                "prot": 0,
                "qos": 0,
                "region": 0,
            },
        )
        self.assertFalse(aw.contains(event))
        self.assertIn("4KB", " ".join(aw.explain(event)))

    def test_illegal_wrap_length_is_rejected(self):
        ar = self.spec.channel("AR").transfer
        event = CanonicalEvent(
            "AR_TRANSFER",
            0,
            {
                "addr": 0x1000,
                "len": 2,
                "size": 2,
                "burst": "WRAP",
                "lock": 0,
                "cache": 0,
                "prot": 0,
                "qos": 0,
                "region": 0,
            },
        )
        self.assertFalse(ar.contains(event))
        self.assertIn("WRAP burst length", " ".join(ar.explain(event)))

    def test_axi4_w_channel_has_no_observable_transaction_id(self):
        event = self.spec.channel("W").transfer.sample(Random(3))
        self.assertIsNone(event.key)

    def test_missing_foundations_are_explicit_not_hidden_in_custom_checker(self):
        self.assertNotIn("ClockedReadyValid", self.spec.missing_foundations)
        self.assertNotIn("ResetEpoch", self.spec.missing_foundations)
        self.assertNotIn("CardinalityObligation", self.spec.missing_foundations)
        self.assertNotIn("CorrelatedCardinalityObligation", self.spec.missing_foundations)
        self.assertNotIn("KeyedFifoToken", self.spec.missing_foundations)

    def test_read_transaction_model_checks_len_plus_one_and_rlast(self):
        model = self.spec.transaction_models["read"]
        ar = self.spec.channel("AR").transfer.sample_constrained(
            Random(23), payload={"len": 1, "size": 2, "burst": "INCR"}
        )
        state = model.step(model.initial_state(), ar).state
        first = model.sample_legal(state, Random(24), allow_begin=False)
        state = model.step(state, first).state
        second = model.sample_legal(state, Random(25), allow_begin=False)
        result = model.run((ar, first, second))
        self.assertEqual(result.verdict, Verdict.PASS)
        self.assertFalse(first.payload["last"])
        self.assertTrue(second.payload["last"])

    def test_all_channels_instantiate_the_shared_ready_valid_monitor(self):
        for channel in self.spec.channels.values():
            self.assertIsInstance(channel.observation_model, ResetEpoch)
            self.assertIsInstance(channel.observation_model.inner, ClockedReadyValid)
            self.assertIs(channel.observation_model.inner.transfer, channel.transfer)

    def test_aw_waveform_lowers_to_an_aw_transfer(self):
        aw = self.spec.channel("AW")
        event = aw.transfer.sample(Random(17))
        result = aw.observation_model.run(
            (
                ResetSample(False, ReadyValidSample(0, True, False, event, "aclk", "axi_monitor")),
                ResetSample(False, ReadyValidSample(1, True, True, event, "aclk", "axi_monitor")),
            )
        )
        self.assertEqual(result.verdict, Verdict.PASS)
        self.assertEqual(result.emissions[0].kind, "AW_TRANSFER")
        self.assertEqual(result.emissions[0].source, "axi_monitor")

    def test_configuration_rejects_non_hardware_data_width(self):
        with self.assertRaisesRegex(ValueError, "power of two"):
            Axi4Config(data_width=48)


if __name__ == "__main__":
    unittest.main()
