from __future__ import annotations

from random import Random
import unittest

from protocol_model import EventOffer, Verdict
from protocol_model.artifacts import protocol_record_from_link
from protocol_model.link.amba.axi.axi4 import (
    Axi4ReadGenerationPolicy,
    Axi4ReadGenerator,
    Axi4ReadSchedule,
    Axi4WriteGenerationPolicy,
    Axi4WriteGenerator,
    build_axi4_link,
    build_axi4_read_link,
)


class Axi4ReadLinkTest(unittest.TestCase):
    def test_monitor_offers_only_enabled_read_actions(self) -> None:
        protocol = build_axi4_read_link()
        session = protocol.open_session()
        state = session.initial_state()

        self.assertEqual({"AR"}, {item.kind for item in session.event_offers(state)})
        with self.assertRaisesRegex(ValueError, "no enabled"):
            session.generate_event(state, Random(1), kind="R")

        request = session.generate_event(
            state,
            Random(2),
            offer=EventOffer.constrained(
                "AR",
                key=3,
                payload={
                    "addr": 0x100,
                    "len": 3,
                    "size": 2,
                    "burst": "INCR",
                    "lock": 0,
                },
            ),
        )
        transition = session.step(state, request)
        self.assertIsNone(transition.fault)

        response_offers = [
            item
            for item in session.event_offers(transition.state)
            if item.kind == "R"
        ]
        self.assertEqual(
            {"OKAY", "SLVERR", "DECERR"},
            {item.payload["resp"] for item in response_offers},
        )
        self.assertTrue(all(item.key == 3 for item in response_offers))
        self.assertTrue(
            all(item.payload["last"] is False for item in response_offers)
        )

    def test_generated_trace_is_accepted_by_the_same_link_protocol(self) -> None:
        protocol = build_axi4_read_link()
        trace = Axi4ReadGenerator(protocol).generate(
            Random(7), Axi4ReadGenerationPolicy(reads=4, maximum_beats=4)
        )

        run = protocol.open_session().run(trace.events)
        requests = [event for event in trace.events if event.kind == "AR"]
        responses = [event for event in trace.events if event.kind == "R"]
        expected_beats = sum(int(event.payload["len"]) + 1 for event in requests)

        self.assertEqual(Verdict.PASS, run.verdict)
        self.assertEqual(4, len(requests))
        self.assertEqual(expected_beats, len(responses))
        self.assertTrue(trace.causal_edges)

    def test_generation_policy_bounds_request_length(self) -> None:
        trace = Axi4ReadGenerator.from_config().generate(
            Random(11), Axi4ReadGenerationPolicy(reads=12, maximum_beats=2)
        )

        self.assertTrue(
            all(
                int(event.payload["len"]) < 2
                for event in trace.events
                if event.kind == "AR"
            )
        )

    def test_cross_id_responses_can_interleave(self) -> None:
        protocol = build_axi4_link()
        trace = Axi4ReadGenerator(protocol).generate(
            Random(13),
            Axi4ReadGenerationPolicy(
                reads=2,
                maximum_beats=2,
                request_ids=(1, 2),
                request_beats=(2, 2),
                response_schedule=Axi4ReadSchedule.INTERLEAVE,
            ),
        )
        responses = [event for event in trace.events if event.kind == "R"]

        self.assertEqual(Verdict.PASS, protocol.open_session().run(trace.events).verdict)
        self.assertEqual([1, 2, 1, 2], [event.key for event in responses])
        self.assertEqual(
            [False, False, True, True],
            [event.payload["last"] for event in responses],
        )

    def test_same_id_reads_complete_in_request_order(self) -> None:
        trace = Axi4ReadGenerator.from_config().generate(
            Random(17),
            Axi4ReadGenerationPolicy(
                reads=2,
                maximum_beats=2,
                request_ids=(3, 3),
                request_beats=(2, 1),
                response_schedule=Axi4ReadSchedule.INTERLEAVE,
            ),
        )
        responses = [event for event in trace.events if event.kind == "R"]

        self.assertEqual([3, 3, 3], [event.key for event in responses])
        self.assertEqual(
            [False, True, True],
            [event.payload["last"] for event in responses],
        )


class Axi4WriteLinkTest(unittest.TestCase):
    def test_generated_writes_are_accepted_by_the_five_channel_link(self) -> None:
        protocol = build_axi4_link()
        trace = Axi4WriteGenerator(protocol).generate(
            Random(23),
            Axi4WriteGenerationPolicy(
                writes=3,
                maximum_beats=4,
                request_ids=(1, 2, 1),
                request_beats=(2, 1, 3),
            ),
        )

        run = protocol.open_session().run(trace.events)
        kinds = [event.kind for event in trace.events]

        self.assertEqual(Verdict.PASS, run.verdict)
        self.assertEqual(3, kinds.count("AW"))
        self.assertEqual(6, kinds.count("W"))
        self.assertEqual(3, kinds.count("B"))
        self.assertTrue(trace.causal_edges)

    def test_w_burst_can_arrive_before_its_aw_descriptor(self) -> None:
        protocol = build_axi4_link()
        session = protocol.open_session()
        state = session.initial_state()
        rng = Random(29)

        data = session.generate_event(
            state,
            rng,
            offer=EventOffer.constrained(
                "W", payload={"strb": 0, "last": True}
            ),
        )
        data_step = session.step(state, data)
        self.assertIsNone(data_step.fault)

        address = session.generate_event(
            data_step.state,
            rng,
            offer=EventOffer.constrained(
                "AW",
                key=4,
                payload={
                    "addr": 0x200,
                    "len": 0,
                    "size": 2,
                    "burst": "INCR",
                },
            ),
        )
        address_step = session.step(data_step.state, address)
        self.assertIsNone(address_step.fault)

        completion = session.generate_event(address_step.state, rng, kind="B")
        completed = session.step(address_step.state, completion)
        self.assertIsNone(completed.fault)
        self.assertTrue(session.is_quiescent(completed.state))

    def test_wlast_is_checked_against_oldest_aw(self) -> None:
        protocol = build_axi4_link()
        session = protocol.open_session()
        state = session.initial_state()
        rng = Random(31)
        address = session.generate_event(
            state,
            rng,
            offer=EventOffer.constrained(
                "AW",
                key=1,
                payload={
                    "addr": 0x300,
                    "len": 1,
                    "size": 2,
                    "burst": "INCR",
                },
            ),
        )
        state = session.step(state, address).state
        early = session.protocol.generate_event(
            EventOffer.constrained(
                "W", payload={"data": 0, "strb": 0, "last": True}
            ),
            rng,
        )

        rejected = session.step(state, early)

        self.assertEqual("axi4.write.final_marker", rejected.fault.rule)


class Axi4ResourceLifecycleTest(unittest.TestCase):
    def test_link_declares_unbounded_transaction_resource_lifecycles(self) -> None:
        protocol = build_axi4_link()
        resources = {item.name: item for item in protocol.semantics.resources}

        self.assertEqual(
            {
                "axi4.read.pending_transactions",
                "axi4.write.assembling_data",
                "axi4.write.pending_descriptors",
                "axi4.write.pending_data_bursts",
                "axi4.write.pending_completions",
                "axi4.exclusive.reservations",
            },
            set(resources),
        )
        self.assertEqual(
            ("AR",), resources["axi4.read.pending_transactions"].acquired_by
        )
        self.assertEqual(
            ("R[last=True]", "reset"),
            resources["axi4.read.pending_transactions"].released_by,
        )
        self.assertEqual(
            ("AW/W FIFO join",),
            resources["axi4.write.pending_completions"].acquired_by,
        )
        self.assertTrue(all(item.capacity is None for item in resources.values()))

    def test_protocol_record_exposes_resource_lifecycle(self) -> None:
        record = protocol_record_from_link(build_axi4_link())
        resources = {
            item["name"]: item for item in record.metadata["resources"]
        }

        self.assertEqual(
            ["B", "reset"],
            list(resources["axi4.write.pending_completions"]["released_by"]),
        )

    def test_runtime_projects_monitor_state_to_resource_usage(self) -> None:
        protocol = build_axi4_link()
        session = protocol.open_session()
        state = session.initial_state()
        rng = Random(37)
        address = session.generate_event(
            state,
            rng,
            offer=EventOffer.constrained(
                "AW",
                key=2,
                payload={
                    "addr": 0x400,
                    "len": 0,
                    "size": 2,
                    "burst": "INCR",
                    "lock": 0,
                },
            ),
        )
        state = session.step(state, address).state
        self.assertEqual(
            1, session.resource_usage(state)["axi4.write.pending_descriptors"]
        )

        data = session.generate_event(state, rng, kind="W")
        state = session.step(state, data).state
        usage = session.resource_usage(state)
        self.assertEqual(0, usage["axi4.write.pending_descriptors"])
        self.assertEqual(1, usage["axi4.write.pending_completions"])

        response = session.generate_event(state, rng, kind="B")
        state = session.step(state, response).state
        self.assertTrue(all(count == 0 for count in session.resource_usage(state).values()))

    def test_bounded_profile_rejects_resource_overflow_and_rolls_back(self) -> None:
        protocol = build_axi4_link().with_resource_capacities(
            "axi4_one_read",
            {"axi4.read.pending_transactions": 1},
        )
        session = protocol.open_session()
        state = session.initial_state()
        rng = Random(43)

        for key in (1, 2):
            request = protocol.generate_event(
                EventOffer.constrained(
                    "AR",
                    key=key,
                    payload={
                        "addr": 0x600 + key * 8,
                        "len": 0,
                        "size": 2,
                        "burst": "INCR",
                        "lock": 0,
                    },
                ),
                rng,
            )
            transition = session.step(state, request)
            if key == 1:
                self.assertIsNone(transition.fault)
                state = transition.state
            else:
                self.assertTrue(transition.fault.rule.endswith("capacity"))
                self.assertEqual(1, session.resource_usage(state)["axi4.read.pending_transactions"])
                self.assertEqual(state, transition.state)


if __name__ == "__main__":
    unittest.main()
