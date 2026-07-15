from __future__ import annotations

import unittest

from protocol_model import AtomicFrame, CanonicalEvent
from protocol_model.link.amba.apb import APB_FAMILY
from protocol_model.link.amba.apb.apb3 import (
    Apb3Config,
    Apb3ObservationSession,
    Apb3Signals,
    build_apb3_link,
)
from protocol_model.link.amba.apb.apb4 import (
    Apb4Config,
    Apb4ObservationSession,
    Apb4Signals,
    build_apb4_link,
)
from protocol_model.link.amba.apb.apb5 import (
    Apb5Config,
    Apb5ObservationSession,
    Apb5Signals,
    build_apb5_link,
)


class ApbLinkTest(unittest.TestCase):
    def test_apb_revisions_have_independent_public_schemas(self) -> None:
        apb3 = build_apb3_link()
        apb4 = build_apb4_link()
        apb5 = build_apb5_link()

        self.assertEqual(APB_FAMILY, apb3.family)
        self.assertEqual(APB_FAMILY, apb4.family)
        self.assertEqual(APB_FAMILY, apb5.family)
        self.assertEqual({"addr"}, set(apb3.channels["READ"].event.fields))
        self.assertEqual(
            {"addr", "prot"}, set(apb4.channels["READ"].event.fields)
        )
        self.assertEqual(
            {"addr", "prot", "data", "strb"},
            set(apb4.channels["WRITE"].event.fields),
        )
        with self.assertRaises(TypeError):
            Apb3Signals(False, False, pprot=0)  # type: ignore[call-arg]

    def test_apb4_resolves_pprot_and_pstrb_independently(self) -> None:
        prot_only = build_apb4_link(
            Apb4Config(pprot_present=True, pstrb_present=False)
        )
        strb_only = build_apb4_link(
            Apb4Config(pprot_present=False, pstrb_present=True)
        )

        self.assertEqual(
            {"addr", "prot", "data"},
            set(prot_only.channels["WRITE"].event.fields),
        )
        self.assertEqual(
            {"addr", "data", "strb"},
            set(strb_only.channels["WRITE"].event.fields),
        )
        self.assertEqual({"addr"}, set(strb_only.channels["READ"].event.fields))

    def test_apb_dimensions_follow_protocol_limits(self) -> None:
        for data_width in (8, 16, 32):
            self.assertEqual(
                data_width,
                build_apb3_link(data_width=data_width).parameters["data_width"],
            )
        with self.assertRaises(ValueError):
            Apb3Config(address_width=33)
        with self.assertRaises(ValueError):
            Apb4Config(data_width=64)

    def test_apb_has_one_pending_transfer_and_typed_completion(self) -> None:
        protocol = build_apb4_link()
        session = protocol.open_session()
        state = session.initial_state()
        request = CanonicalEvent(
            "READ", None, {"addr": 0x10, "prot": 0}
        )
        opened = session.step(state, request)
        self.assertEqual(
            {"READ_RESPONSE"},
            {offer.kind for offer in session.event_offers(opened.state)},
        )
        second = session.step(
            opened.state,
            CanonicalEvent(
                "WRITE",
                None,
                {"addr": 0x14, "prot": 0, "data": 1, "strb": 0b1111},
            ),
        )
        wrong_response = session.step(
            opened.state,
            CanonicalEvent("WRITE_RESPONSE", None, {"error": False}),
        )

        self.assertIsNone(opened.fault)
        self.assertTrue(second.fault.rule.endswith("capacity"))
        self.assertEqual(
            "apb.transfer.completion_order", wrong_response.fault.rule
        )

    def test_apb3_observer_uses_its_native_signal_type(self) -> None:
        observer = Apb3ObservationSession()
        setup = observer.step(
            observer.initial_state(),
            AtomicFrame(
                0,
                "pclk",
                {
                    "APB": Apb3Signals(True, False, paddr=0x24),
                    "reset": False,
                },
                "apb3-pins",
            ),
        )
        completed = observer.step(
            setup.state,
            AtomicFrame(
                1,
                "pclk",
                {
                    "APB": Apb3Signals(
                        True, True, paddr=0x24, prdata=0x55
                    ),
                    "reset": False,
                },
                "apb3-pins",
            ),
        )

        self.assertEqual("READ", setup.emissions[0].kind)
        self.assertEqual(
            {"data": 0x55, "error": False},
            dict(completed.emissions[0].payload),
        )

    def test_apb5_schema_carries_user_and_rme_attributes(self) -> None:
        config = Apb5Config(
            wakeup_signal=True,
            user_request_width=4,
            user_data_width=8,
            user_response_width=3,
            rme_support=True,
        )
        protocol = build_apb5_link(config)

        self.assertEqual(
            {"addr", "prot", "nse", "auser"},
            set(protocol.channels["READ"].event.fields),
        )
        self.assertEqual(
            {"addr", "prot", "nse", "auser", "data", "strb", "wuser"},
            set(protocol.channels["WRITE"].event.fields),
        )
        self.assertEqual(
            {"data", "error", "ruser", "buser"},
            set(protocol.channels["READ_RESPONSE"].event.fields),
        )
        self.assertEqual(
            {"error", "buser"},
            set(protocol.channels["WRITE_RESPONSE"].event.fields),
        )
        self.assertEqual("none", protocol.parameters["check_type"])
        with self.assertRaises(ValueError):
            Apb5Config(rme_support=True, pprot_present=False)
        with self.assertRaises(ValueError):
            Apb5Config(check_type="Odd_Parity_Byte_All")  # type: ignore[arg-type]


class Apb4ObservationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.observer = Apb4ObservationSession()

    @staticmethod
    def frame(
        tick: int, signals: Apb4Signals, *, reset: bool = False
    ) -> AtomicFrame:
        return AtomicFrame(
            tick, "pclk", {"APB": signals, "reset": reset}, "apb4-pins"
        )

    def reset_state(self):
        reset = self.observer.step(
            self.observer.initial_state(),
            self.frame(0, Apb4Signals(False, False), reset=True),
        )
        self.assertIsNone(reset.fault)
        return reset.state

    def test_setup_wait_and_completed_access(self) -> None:
        state = self.reset_state()
        setup_signals = Apb4Signals(
            True,
            False,
            paddr=0x20,
            pwrite=True,
            pwdata=5,
            pstrb=0b1111,
            pprot=1,
        )
        setup = self.observer.step(state, self.frame(1, setup_signals))
        waited = self.observer.step(
            setup.state,
            self.frame(
                2,
                Apb4Signals(
                    **{
                        **setup_signals.__dict__,
                        "penable": True,
                        "pready": False,
                    }
                ),
            ),
        )
        completed = self.observer.step(
            waited.state,
            self.frame(
                3,
                Apb4Signals(
                    **{
                        **setup_signals.__dict__,
                        "penable": True,
                        "pready": True,
                    }
                ),
            ),
        )

        self.assertEqual(("WRITE",), tuple(e.kind for e in setup.emissions))
        self.assertFalse(waited.emissions)
        self.assertEqual(
            ("WRITE_RESPONSE",), tuple(e.kind for e in completed.emissions)
        )
        self.assertTrue(self.observer.is_quiescent(completed.state))

    def test_request_stability_and_optional_signal_policy(self) -> None:
        state = self.reset_state()
        setup = self.observer.step(
            state,
            self.frame(
                1,
                Apb4Signals(True, False, paddr=0x30, pwrite=False),
            ),
        )
        changed = self.observer.step(
            setup.state,
            self.frame(
                2,
                Apb4Signals(
                    True,
                    True,
                    False,
                    paddr=0x34,
                    pwrite=False,
                ),
            ),
        )
        strobed_read = self.observer.step(
            state,
            self.frame(
                1,
                Apb4Signals(
                    True, False, paddr=0x30, pwrite=False, pstrb=1
                ),
            ),
        )
        no_extensions = Apb4ObservationSession(
            config=Apb4Config(pprot_present=False, pstrb_present=False)
        )
        absent = no_extensions.step(
            no_extensions.initial_state(),
            AtomicFrame(
                0,
                "pclk",
                {
                    "APB": Apb4Signals(False, False, pprot=1),
                    "reset": False,
                },
                "apb4-pins",
            ),
        )

        self.assertTrue(changed.fault.rule.endswith("request_stability"))
        self.assertTrue(strobed_read.fault.rule.endswith("read_strobe"))
        self.assertTrue(absent.fault.rule.endswith("absent_pprot"))


class Apb5ObservationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Apb5Config(
            wakeup_signal=True,
            user_request_width=4,
            user_data_width=8,
            user_response_width=3,
            rme_support=True,
        )
        self.observer = Apb5ObservationSession(config=self.config)

    @staticmethod
    def frame(
        tick: int, signals: Apb5Signals, *, reset: bool = False
    ) -> AtomicFrame:
        return AtomicFrame(
            tick, "pclk", {"APB": signals, "reset": reset}, "apb5-pins"
        )

    def test_wakeup_hold_and_user_rme_lowering(self) -> None:
        reset = self.observer.step(
            self.observer.initial_state(),
            self.frame(0, Apb5Signals(False, False), reset=True),
        )
        setup_signals = Apb5Signals(
            True,
            False,
            False,
            paddr=0x40,
            pwrite=True,
            pwdata=0xA5,
            pstrb=0b1111,
            pprot=0b010,
            pnse=True,
            pwakeup=True,
            pauser=0xA,
            pwuser=0x5A,
        )
        setup = self.observer.step(
            reset.state, self.frame(1, setup_signals)
        )
        dropped_wakeup = self.observer.step(
            setup.state,
            self.frame(
                2,
                Apb5Signals(
                    **{
                        **setup_signals.__dict__,
                        "penable": True,
                        "pwakeup": False,
                    }
                ),
            ),
        )
        waited = self.observer.step(
            setup.state,
            self.frame(
                2,
                Apb5Signals(
                    **{**setup_signals.__dict__, "penable": True}
                ),
            ),
        )
        completed = self.observer.step(
            waited.state,
            self.frame(
                3,
                Apb5Signals(
                    **{
                        **setup_signals.__dict__,
                        "penable": True,
                        "pready": True,
                        "pbuser": 0b101,
                    }
                ),
            ),
        )

        request = setup.emissions[0]
        response = completed.emissions[0]
        self.assertEqual(
            {
                "addr": 0x40,
                "prot": 0b010,
                "nse": True,
                "auser": 0xA,
                "data": 0xA5,
                "strb": 0b1111,
                "wuser": 0x5A,
            },
            dict(request.payload),
        )
        self.assertTrue(dropped_wakeup.fault.rule.endswith("wakeup_hold"))
        self.assertFalse(waited.emissions)
        self.assertEqual(
            {"error": False, "buser": 0b101}, dict(response.payload)
        )
        self.assertTrue(self.observer.is_quiescent(completed.state))

        read_setup_signals = Apb5Signals(
            True,
            False,
            paddr=0x44,
            pprot=0b010,
            pnse=True,
            pauser=0x3,
        )
        read_setup = self.observer.step(
            completed.state, self.frame(4, read_setup_signals)
        )
        read_completed = self.observer.step(
            read_setup.state,
            self.frame(
                5,
                Apb5Signals(
                    **{
                        **read_setup_signals.__dict__,
                        "penable": True,
                        "prdata": 0xCAFE,
                        "pruser": 0x7E,
                        "pbuser": 0b011,
                    }
                ),
            ),
        )
        self.assertEqual(
            {
                "data": 0xCAFE,
                "error": False,
                "ruser": 0x7E,
                "buser": 0b011,
            },
            dict(read_completed.emissions[0].payload),
        )


if __name__ == "__main__":
    unittest.main()
