from __future__ import annotations

import unittest

from protocol_model import AtomicFrame, CanonicalEvent, Verdict
from protocol_model.link.amba.ahb.ahb5 import Ahb5Config, build_ahb5_link
from protocol_model.link.amba.ahb.ahb_lite import (
    AhbLiteConfig,
    AhbObservationSession,
    AhbSignals,
    build_ahb_lite_link,
)


def read(addr: int, *, burst: str = "SINGLE", trans: str = "NONSEQ") -> CanonicalEvent:
    return CanonicalEvent(
        "READ",
        None,
        {"addr": addr, "size": 2, "burst": burst, "trans": trans, "prot": 1, "lock": False},
    )


def read_response(data: int = 0, resp: str = "OKAY") -> CanonicalEvent:
    return CanonicalEvent("READ_RESPONSE", None, {"data": data, "resp": resp})


class AhbLiteLinkTest(unittest.TestCase):
    def test_single_transfer_and_fixed_burst(self) -> None:
        protocol = build_ahb_lite_link()
        single = protocol.open_session().run((read(0x100), read_response(3)))
        burst_events = []
        for index in range(4):
            burst_events.extend(
                (
                    read(
                        0x200 + 4 * index,
                        burst="INCR4",
                        trans="NONSEQ" if index == 0 else "SEQ",
                    ),
                    read_response(index),
                )
            )
        burst = protocol.open_session().run(burst_events)

        self.assertEqual(Verdict.PASS, single.verdict)
        self.assertEqual(Verdict.PASS, burst.verdict)

    def test_alignment_and_burst_address_sequence_are_checked(self) -> None:
        protocol = build_ahb_lite_link()
        session = protocol.open_session()
        misaligned = session.step(session.initial_state(), read(0x102))

        first = session.step(session.initial_state(), read(0x200, burst="INCR4"))
        first_done = session.step(first.state, read_response())
        wrong = session.step(
            first_done.state, read(0x208, burst="INCR4", trans="SEQ")
        )

        self.assertTrue(misaligned.fault.rule.endswith("event_schema"))
        self.assertEqual("ahb.burst.address_sequence", wrong.fault.rule)

    def test_ahb_lite_write_data_has_no_issue_c_strobe_field(self) -> None:
        protocol = build_ahb_lite_link()
        write_data = CanonicalEvent(
            "WRITE_DATA", None, {"data": 0, "strb": 0b0001}
        )
        transition = protocol.open_session().step(
            protocol.open_session().initial_state(), write_data
        )

        self.assertTrue(transition.fault.rule.endswith("event_schema"))


class Ahb5LinkTest(unittest.TestCase):
    @staticmethod
    def write(*, exclusive: bool = False, burst: str = "SINGLE") -> CanonicalEvent:
        return CanonicalEvent(
            "WRITE",
            None,
            {
                "addr": 0x102,
                "size": 1,
                "burst": burst,
                "trans": "NONSEQ",
                "prot": 0,
                "lock": False,
                "exclusive": exclusive,
                "master": 2,
            },
        )

    def test_issue_c_properties_shape_the_payload(self) -> None:
        protocol = build_ahb5_link(
            Ahb5Config(
                extended_memory_types=True,
                secure_transfers=True,
                write_strobes=True,
                user_request_width=3,
                user_data_width=4,
                user_response_width=2,
            )
        )
        self.assertEqual(7, protocol.channels["READ"].event.fields["prot"].domain.width)
        self.assertIn("nonsecure", protocol.channels["READ"].event.fields)
        self.assertIn("auser", protocol.channels["WRITE"].event.fields)
        self.assertIn("strb", protocol.channels["WRITE_DATA"].event.fields)
        self.assertIn("wuser", protocol.channels["WRITE_DATA"].event.fields)
        self.assertIn("ruser", protocol.channels["READ_RESPONSE"].event.fields)
        self.assertIn("buser", protocol.channels["WRITE_RESPONSE"].event.fields)

    def test_write_strobes_are_sparse_write_attributes_not_lane_legality(self) -> None:
        protocol = build_ahb5_link(Ahb5Config(write_strobes=True))
        events = (
            CanonicalEvent(
                "WRITE",
                None,
                {
                    "addr": 0x102,
                    "size": 1,
                    "burst": "SINGLE",
                    "trans": "NONSEQ",
                    "prot": 0,
                    "lock": False,
                },
            ),
            CanonicalEvent("WRITE_DATA", None, {"data": 0, "strb": 0b0001}),
            CanonicalEvent("WRITE_RESPONSE", None, {"resp": "OKAY"}),
        )

        result = protocol.open_session().run(events)
        self.assertEqual(Verdict.PASS, result.verdict)

    def test_exclusive_shape_and_response_signaling_are_link_checked(self) -> None:
        protocol = build_ahb5_link(Ahb5Config(exclusive_transfers=True))
        session = protocol.open_session()
        bad_shape = session.step(
            session.initial_state(), self.write(exclusive=True, burst="INCR4")
        )

        opened = session.step(session.initial_state(), self.write(exclusive=False))
        data = session.step(
            opened.state, CanonicalEvent("WRITE_DATA", None, {"data": 0})
        )
        bad_response = session.step(
            data.state,
            CanonicalEvent(
                "WRITE_RESPONSE",
                None,
                {"resp": "OKAY", "exclusive_ok": True},
            ),
        )

        self.assertTrue(bad_shape.fault.rule.endswith("event_schema"))
        self.assertEqual(
            "ahb5.exclusive_signaling.nonexclusive_success",
            bad_response.fault.rule,
        )


class AhbObservationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.observer = AhbObservationSession()

    @staticmethod
    def frame(tick: int, signals: AhbSignals, *, reset: bool = False) -> AtomicFrame:
        return AtomicFrame(tick, "hclk", {"AHB": signals, "reset": reset}, "ahb-pins")

    def reset_state(self):
        reset = self.observer.step(
            self.observer.initial_state(),
            self.frame(0, AhbSignals(False, True), reset=True),
        )
        self.assertIsNone(reset.fault)
        return reset.state

    def test_address_and_data_phases_overlap(self) -> None:
        state = self.reset_state()
        accepted_a = self.observer.step(
            state,
            self.frame(
                1,
                AhbSignals(True, True, "NONSEQ", 0x100, False, 2, "SINGLE", 1),
            ),
        )
        complete_a_accept_b = self.observer.step(
            accepted_a.state,
            self.frame(
                2,
                AhbSignals(
                    True,
                    True,
                    "NONSEQ",
                    0x104,
                    True,
                    2,
                    "SINGLE",
                    1,
                    hwdata=0,
                    hrdata=7,
                ),
            ),
        )
        complete_b = self.observer.step(
            complete_a_accept_b.state,
            self.frame(3, AhbSignals(False, True, hwdata=9)),
        )

        self.assertEqual(("READ",), tuple(event.kind for event in accepted_a.emissions))
        self.assertEqual(
            ("READ_RESPONSE", "WRITE"),
            tuple(event.kind for event in complete_a_accept_b.emissions),
        )
        self.assertEqual(
            ("WRITE_DATA", "WRITE_RESPONSE"),
            tuple(event.kind for event in complete_b.emissions),
        )
        self.assertTrue(self.observer.is_quiescent(complete_b.state))

    def test_active_address_and_write_data_are_stable_during_wait(self) -> None:
        state = self.reset_state()
        accepted = self.observer.step(
            state,
            self.frame(
                1,
                AhbSignals(True, True, "NONSEQ", 0x100, True, 2, "SINGLE", 0),
            ),
        )
        waited = self.observer.step(
            accepted.state,
            self.frame(
                2,
                AhbSignals(True, False, "NONSEQ", 0x200, False, 2, "SINGLE", 0, hwdata=3),
            ),
        )
        changed = self.observer.step(
            waited.state,
            self.frame(
                3,
                AhbSignals(True, False, "NONSEQ", 0x204, False, 2, "SINGLE", 0, hwdata=3),
            ),
        )

        self.assertIsNone(waited.fault)
        self.assertTrue(changed.fault.rule.endswith("address_stability"))

    def test_error_response_requires_two_cycles(self) -> None:
        state = self.reset_state()
        accepted = self.observer.step(
            state,
            self.frame(
                1,
                AhbSignals(True, True, "NONSEQ", 0x100, False, 2, "SINGLE", 0),
            ),
        )
        first_error = self.observer.step(
            accepted.state,
            self.frame(2, AhbSignals(False, False, hresp="ERROR")),
        )
        completed = self.observer.step(
            first_error.state,
            self.frame(3, AhbSignals(False, True, hresp="ERROR")),
        )

        self.assertIsNone(first_error.fault)
        self.assertIsNone(completed.fault)
        self.assertEqual("ERROR", completed.emissions[0].payload["resp"])


if __name__ == "__main__":
    unittest.main()
