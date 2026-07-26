from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.endpoints import (
    build_axi4_address_space_vdut,
)
from protocol_model.integrations.recipes.amba.fabrics import (
    Axi4ReadRouteTableProfile,
    build_axi4_read_crossbar_vdut,
)
from protocol_model.integrations.backends.amba.axi.axi4.read import (
    Axi4ReadCrossbarBackend,
    Axi4ReadCrossbarState,
)
from protocol_model.protocols.amba.axi.axi4 import (
    Axi4Config,
    build_axi4_interface,
    build_axi4_read_only_profile,
)
from protocol_model.semantics import CanonicalEvent
from protocol_model.system import (
    AddressClaim,
    AddressRouterContract,
    AddressWindow,
    DutAdvanceAction,
    SystemAction,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut import (
    AddressRoute,
    AddressSpace,
    CaptureBackend,
    InterfacePort,
    MemoryRegion,
    SteppedEmissionProfile,
    VirtualDut,
)
from protocol_model.virtual_dut.backend import CaptureState


TARGET_BASES = (0x1000, 0x2000, 0x3000, 0x4000)
TARGET_BYTES = 0x100


def _ar(
    read_id: int,
    address: int,
    *,
    length: int = 0,
    lock: int = 0,
) -> CanonicalEvent:
    return CanonicalEvent(
        "AR",
        read_id,
        {
            "addr": address,
            "len": length,
            "size": 2,
            "burst": "INCR",
            "lock": lock,
            "cache": 0,
            "prot": 0,
            "qos": 0,
            "region": 0,
        },
    )


class Axi4ReadCrossbarTest(unittest.TestCase):
    @staticmethod
    def _manager(name: str, protocol) -> VirtualDut:
        return VirtualDut(
            name,
            {"axi": InterfacePort("axi", protocol, "manager")},
            backend=CaptureBackend(),
        )

    @staticmethod
    def _target(
        name: str,
        protocol,
        first_word: int,
        *,
        response_capacity_events: int,
    ) -> VirtualDut:
        content = b"".join(
            word.to_bytes(4, byteorder="little")
            for word in range(first_word, first_word + 4)
        )
        return build_axi4_address_space_vdut(
            name,
            protocol,
            AddressSpace(
                (
                    MemoryRegion(
                        f"{name}_ram",
                        TARGET_BYTES,
                        initial_content=content,
                    ),
                )
            ),
            response_profile=SteppedEmissionProfile(
                capacity_events=response_capacity_events
            ),
        )

    def _system(
        self,
        *,
        table_profile: Axi4ReadRouteTableProfile | None = None,
        response_capacity_events: int = 16,
    ):
        protocol = build_axi4_read_only_profile(
            Axi4Config(data_width=32, id_width=3)
        )
        routes = tuple(
            AddressRoute(
                f"target{index}",
                base,
                TARGET_BYTES,
                f"m{index}",
                output_base_address=0,
            )
            for index, base in enumerate(TARGET_BASES)
        )
        contract = AddressRouterContract(
            "main_map",
            "crossbar",
            ("s0", "s1"),
            tuple(f"m{index}" for index in range(4)),
            routes,
        )
        builder = SystemProtocolBuilder("axi4_read_two_by_four")
        for dut in (
            self._manager("manager0", protocol),
            self._manager("manager1", protocol),
            *(
                self._target(
                    f"target{index}",
                    protocol,
                    (index + 1) * 0x10 + 1,
                    response_capacity_events=response_capacity_events,
                )
                for index in range(4)
            ),
        ):
            builder.add_dut(dut)
        builder.construct_address_router(
            contract,
            lambda received: build_axi4_read_crossbar_vdut(
                received.router,
                protocol,
                received.ingress_ports,
                received.egress_ports,
                received.routes,
                table_profile=table_profile,
            ),
        )
        for index in range(2):
            builder.connect(
                f"manager{index}_bus",
                protocol,
                {
                    "manager": VirtualDutPortRef(
                        f"manager{index}", "axi"
                    ),
                    "subordinate": VirtualDutPortRef(
                        "crossbar", f"s{index}"
                    ),
                },
            )
        for index in range(4):
            builder.connect(
                f"target{index}_bus",
                protocol,
                {
                    "manager": VirtualDutPortRef(
                        "crossbar", f"m{index}"
                    ),
                    "subordinate": VirtualDutPortRef(
                        f"target{index}", "axi"
                    ),
                },
            )
            builder.add_address_claim(
                AddressClaim(
                    f"target{index}_local",
                    VirtualDutPortRef(f"target{index}", "axi"),
                    AddressWindow(0, TARGET_BYTES),
                )
            )
        return builder.build()

    @staticmethod
    def _issue(
        manager: int,
        read_id: int,
        address: int,
        *,
        length: int = 0,
        lock: int = 0,
    ) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef(f"manager{manager}", "axi"),
            _ar(read_id, address, length=length, lock=lock),
        )

    @staticmethod
    def _captured(state, manager: int) -> tuple[CanonicalEvent, ...]:
        capture = state.dut_states[f"manager{manager}"]
        if not isinstance(capture, CaptureState):
            raise TypeError("test expected CaptureState")
        return tuple(item.event for item in capture.received)

    def test_two_by_four_shape_resolves_every_manager_route(self) -> None:
        system = self._system()
        plan = system.elaborate().address_plan
        assert plan is not None
        self.assertEqual(8, len(plan.paths))
        crossbar = system.virtual_duts["crossbar"]
        self.assertIsInstance(crossbar.backend, Axi4ReadCrossbarBackend)
        assert isinstance(crossbar.backend, Axi4ReadCrossbarBackend)
        self.assertEqual(("s0", "s1"), crossbar.backend.ingress_ports)
        self.assertEqual(
            ("m0", "m1", "m2", "m3"), crossbar.backend.egress_ports
        )

    def test_same_raw_rid_on_one_egress_uses_owner_acceptance_order(self) -> None:
        system = self._system()
        session = system.open_session()
        first = session.step(
            session.initial_state(), self._issue(0, 3, 0x3000)
        )
        second = session.step(
            first.state, self._issue(1, 3, 0x3004)
        )

        backend = system.virtual_duts["crossbar"].backend
        assert isinstance(backend, Axi4ReadCrossbarBackend)
        state = second.state.dut_states["crossbar"]
        assert isinstance(state, Axi4ReadCrossbarState)
        owners = backend.return_owner_queues(state)[("m2", 3)]
        self.assertEqual(("s0", "s1"), tuple(
            item.ingress_port for item in owners
        ))

        manager0_done = session.step(
            second.state, DutAdvanceAction("target2")
        )
        manager1_done = session.step(
            manager0_done.state, DutAdvanceAction("target2")
        )
        self.assertEqual(
            0x31,
            self._captured(manager1_done.state, 0)[0].payload["data"],
        )
        self.assertEqual(
            0x32,
            self._captured(manager1_done.state, 1)[0].payload["data"],
        )
        self.assertTrue(session.is_quiescent(manager1_done.state))

    def test_same_raw_rid_keeps_multibeat_owner_until_rlast(self) -> None:
        system = self._system()
        session = system.open_session()
        first = session.step(
            session.initial_state(),
            self._issue(0, 3, 0x3000, length=1),
        )
        second = session.step(first.state, self._issue(1, 3, 0x3008))

        first_beat = session.step(
            second.state, DutAdvanceAction("target2")
        )
        backend = system.virtual_duts["crossbar"].backend
        assert isinstance(backend, Axi4ReadCrossbarBackend)
        crossbar = first_beat.state.dut_states["crossbar"]
        assert isinstance(crossbar, Axi4ReadCrossbarState)
        owners = backend.return_owner_queues(crossbar)[("m2", 3)]
        self.assertEqual(("s0", "s1"), tuple(
            item.ingress_port for item in owners
        ))
        self.assertEqual(1, owners[0].remaining_beats)
        self.assertEqual(1, len(self._captured(first_beat.state, 0)))
        self.assertEqual(0, len(self._captured(first_beat.state, 1)))

        first_last = session.step(
            first_beat.state, DutAdvanceAction("target2")
        )
        second_last = session.step(
            first_last.state, DutAdvanceAction("target2")
        )
        self.assertEqual(
            (False, True),
            tuple(
                event.payload["last"]
                for event in self._captured(first_last.state, 0)
            ),
        )
        self.assertEqual(
            (0x31, 0x32),
            tuple(
                event.payload["data"]
                for event in self._captured(first_last.state, 0)
            ),
        )
        self.assertEqual(
            0x33,
            self._captured(second_last.state, 1)[0].payload["data"],
        )
        self.assertTrue(session.is_quiescent(second_last.state))

    def test_one_manager_same_rid_cannot_change_target_until_rlast(self) -> None:
        system = self._system()
        session = system.open_session()
        first = session.step(
            session.initial_state(),
            self._issue(0, 1, 0x1000, length=1),
        )
        blocked = session.step(first.state, self._issue(0, 1, 0x2000))
        self.assertIsNotNone(blocked.blocked)
        assert blocked.blocked is not None
        self.assertEqual(
            "crossbar.axi4_read_id_destination", blocked.blocked.resource
        )
        self.assertIs(blocked.state, first.state)

        first_beat = session.step(
            first.state, DutAdvanceAction("target0")
        )
        still_blocked = session.step(
            first_beat.state, self._issue(0, 1, 0x2000)
        )
        self.assertIsNotNone(still_blocked.blocked)
        last_beat = session.step(
            first_beat.state, DutAdvanceAction("target0")
        )
        retried = session.step(
            last_beat.state, self._issue(0, 1, 0x2000)
        )
        self.assertIsNone(retried.blocked)
        state = retried.state.dut_states["crossbar"]
        assert isinstance(state, Axi4ReadCrossbarState)
        self.assertEqual("m1", state.pending[0].egress_port)

    def test_same_rid_on_different_managers_and_targets_is_independent(self) -> None:
        system = self._system()
        session = system.open_session()
        first = session.step(
            session.initial_state(), self._issue(0, 2, 0x1000)
        )
        second = session.step(first.state, self._issue(1, 2, 0x4000))

        later_first = session.step(
            second.state, DutAdvanceAction("target3")
        )
        earlier_second = session.step(
            later_first.state, DutAdvanceAction("target0")
        )
        self.assertEqual(
            0x41,
            self._captured(earlier_second.state, 1)[0].payload["data"],
        )
        self.assertEqual(
            0x11,
            self._captured(earlier_second.state, 0)[0].payload["data"],
        )
        self.assertTrue(session.is_quiescent(earlier_second.state))

    def test_active_id_capacity_is_independent_per_ingress(self) -> None:
        system = self._system(
            table_profile=Axi4ReadRouteTableProfile(
                active_id_capacity=1,
                outstanding_bursts_per_id=2,
            )
        )
        session = system.open_session()
        manager0_first = session.step(
            session.initial_state(), self._issue(0, 1, 0x1000)
        )
        manager0_blocked = session.step(
            manager0_first.state, self._issue(0, 2, 0x2000)
        )
        self.assertIsNotNone(manager0_blocked.blocked)
        assert manager0_blocked.blocked is not None
        self.assertEqual(
            "crossbar.axi4_read_route_table",
            manager0_blocked.blocked.resource,
        )

        manager1_accepted = session.step(
            manager0_first.state, self._issue(1, 2, 0x2000)
        )
        self.assertIsNone(manager1_accepted.blocked)
        manager0_done = session.step(
            manager1_accepted.state, DutAdvanceAction("target0")
        )
        retried = session.step(
            manager0_done.state, self._issue(0, 2, 0x3000)
        )
        self.assertIsNone(retried.blocked)

    def test_downstream_backpressure_rolls_back_owner_append(self) -> None:
        system = self._system(response_capacity_events=1)
        session = system.open_session()
        first = session.step(
            session.initial_state(), self._issue(0, 1, 0x1000)
        )
        blocked = session.step(first.state, self._issue(1, 2, 0x1004))

        self.assertIsNotNone(blocked.blocked)
        self.assertIs(blocked.state, first.state)
        crossbar = blocked.state.dut_states["crossbar"]
        assert isinstance(crossbar, Axi4ReadCrossbarState)
        self.assertEqual(1, len(crossbar.pending))
        self.assertEqual("s0", crossbar.pending[0].ingress_port)

        drained = session.step(
            first.state, DutAdvanceAction("target0")
        )
        retried = session.step(drained.state, self._issue(1, 2, 0x1004))
        self.assertIsNone(retried.blocked)
        crossbar = retried.state.dut_states["crossbar"]
        assert isinstance(crossbar, Axi4ReadCrossbarState)
        self.assertEqual(("s1",), tuple(
            item.ingress_port for item in crossbar.pending
        ))

    def test_decode_error_ordering_is_local_to_ingress_and_rid(self) -> None:
        system = self._system()
        session = system.open_session()
        first = session.step(
            session.initial_state(),
            self._issue(0, 1, 0x1000, length=1),
        )
        same_domain = session.step(
            first.state, self._issue(0, 1, 0x5000)
        )
        self.assertIsNotNone(same_domain.blocked)
        self.assertIs(same_domain.state, first.state)

        other_ingress = session.step(
            first.state, self._issue(1, 1, 0x5000, length=1)
        )
        responses = self._captured(other_ingress.state, 1)
        self.assertEqual(2, len(responses))
        self.assertEqual(("DECERR", "DECERR"), tuple(
            event.payload["resp"] for event in responses
        ))
        self.assertEqual((False, True), tuple(
            event.payload["last"] for event in responses
        ))
        crossbar = other_ingress.state.dut_states["crossbar"]
        assert isinstance(crossbar, Axi4ReadCrossbarState)
        self.assertEqual(("s0",), tuple(
            item.ingress_port for item in crossbar.pending
        ))

    def test_multi_ingress_raw_id_profile_rejects_exclusive_ar(self) -> None:
        system = self._system()
        session = system.open_session()
        result = session.step(
            session.initial_state(), self._issue(0, 1, 0x1000, lock=1)
        )
        self.assertIsNotNone(result.fault)
        assert result.fault is not None
        self.assertEqual(
            "axi4_read_crossbar.raw_id_exclusive", result.fault.rule
        )

    def test_full_axi_protocol_is_rejected_at_construction(self) -> None:
        protocol = build_axi4_interface(
            Axi4Config(data_width=32, id_width=3)
        )
        routes = (
            AddressRoute("target0", 0x1000, TARGET_BYTES, "m0", 0),
        )
        with self.assertRaisesRegex(
            ValueError,
            "requires an AR/R-only interface",
        ):
            build_axi4_read_crossbar_vdut(
                "crossbar",
                protocol,
                ("s0", "s1"),
                ("m0",),
                routes,
            )


if __name__ == "__main__":
    unittest.main()
