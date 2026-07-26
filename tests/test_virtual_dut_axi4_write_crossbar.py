from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.fabrics import (
    Axi4BurstAssemblyProfile,
    Axi4WriteRouteTableProfile,
    build_axi4_write_crossbar_vdut,
)
from protocol_model.integrations.backends.amba.axi.axi4.write import (
    Axi4WriteCrossbarBackend,
    Axi4WriteCrossbarState,
)
from protocol_model.protocols.amba.axi.axi4 import (
    Axi4Config,
    build_axi4_interface,
    build_axi4_write_only_profile,
)
from protocol_model.semantics import CanonicalEvent
from protocol_model.system import (
    AddressClaim,
    AddressRouterContract,
    AddressWindow,
    SystemAction,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut import (
    AddressRoute,
    CaptureBackend,
    InterfacePort,
    PortInput,
    VirtualDut,
)
from protocol_model.virtual_dut.backend import CaptureState


TARGET_BASES = (0x1000, 0x2000, 0x3000, 0x4000)
TARGET_BYTES = 0x100


def _aw(
    write_id: int,
    address: int,
    *,
    length: int = 0,
    lock: int = 0,
) -> CanonicalEvent:
    return CanonicalEvent(
        "AW",
        write_id,
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


def _w(data: int, *, last: bool, strb: int = 0b1111) -> CanonicalEvent:
    return CanonicalEvent(
        "W",
        None,
        {"data": data, "strb": strb, "last": last},
    )


def _b(write_id: int, response: str = "OKAY") -> CanonicalEvent:
    return CanonicalEvent("B", write_id, {"resp": response})


class Axi4WriteCrossbarTest(unittest.TestCase):
    @staticmethod
    def _capture_endpoint(name: str, protocol, role: str) -> VirtualDut:
        return VirtualDut(
            name,
            {"axi": InterfacePort("axi", protocol, role)},
            backend=CaptureBackend(),
        )

    def _system(
        self,
        *,
        assembly_profile: Axi4BurstAssemblyProfile | None = None,
        table_profile: Axi4WriteRouteTableProfile | None = None,
    ):
        protocol = build_axi4_write_only_profile(
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
        builder = SystemProtocolBuilder("axi4_write_two_by_four")
        for dut in (
            self._capture_endpoint("manager0", protocol, "manager"),
            self._capture_endpoint("manager1", protocol, "manager"),
            *(
                self._capture_endpoint(
                    f"target{index}", protocol, "subordinate"
                )
                for index in range(4)
            ),
        ):
            builder.add_dut(dut)
        builder.construct_address_router(
            contract,
            lambda received: build_axi4_write_crossbar_vdut(
                received.router,
                protocol,
                received.ingress_ports,
                received.egress_ports,
                received.routes,
                assembly_profile=assembly_profile,
                table_profile=table_profile,
            ),
        )
        for index in range(2):
            builder.connect(
                f"manager{index}_bus",
                protocol,
                {
                    "manager": VirtualDutPortRef(f"manager{index}", "axi"),
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
    def _manager_action(manager: int, event: CanonicalEvent) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef(f"manager{manager}", "axi"), event
        )

    @staticmethod
    def _target_response(target: int, write_id: int) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef(f"target{target}", "axi"), _b(write_id)
        )

    @staticmethod
    def _captured(state, dut: str) -> tuple[CanonicalEvent, ...]:
        capture = state.dut_states[dut]
        if not isinstance(capture, CaptureState):
            raise TypeError("test expected CaptureState")
        return tuple(item.event for item in capture.received)

    @staticmethod
    def _write(
        session,
        state,
        manager: int,
        write_id: int,
        address: int,
        *data: int,
    ):
        current = session.step(
            state,
            Axi4WriteCrossbarTest._manager_action(
                manager,
                _aw(write_id, address, length=len(data) - 1),
            ),
        )
        for index, value in enumerate(data):
            current = session.step(
                current.state,
                Axi4WriteCrossbarTest._manager_action(
                    manager,
                    _w(value, last=index == len(data) - 1),
                ),
            )
        return current

    def test_shape_and_store_then_forward_batch(self) -> None:
        system = self._system()
        protocol = system.interface_connections["manager0_bus"].protocol
        self.assertEqual(
            frozenset(("AW", "W", "B")), protocol.enabled_event_kinds
        )
        self.assertEqual(
            frozenset(("AR", "R")), protocol.forbidden_event_kinds
        )
        plan = system.elaborate().address_plan
        assert plan is not None
        self.assertEqual(8, len(plan.paths))

        session = system.open_session()
        initial = session.initial_state()
        address = session.step(
            initial, self._manager_action(0, _aw(1, 0x1000, length=1))
        )
        first_data = session.step(
            address.state,
            self._manager_action(0, _w(0x11111111, last=False)),
        )
        self.assertEqual((), self._captured(first_data.state, "target0"))

        final_data = session.step(
            first_data.state,
            self._manager_action(0, _w(0x22222222, last=True)),
        )
        forwarded = self._captured(final_data.state, "target0")
        self.assertEqual(("AW", "W", "W"), tuple(x.kind for x in forwarded))
        self.assertEqual(0, forwarded[0].payload["addr"])
        self.assertEqual(
            (0x11111111, 0x22222222),
            tuple(x.payload["data"] for x in forwarded[1:]),
        )
        self.assertEqual((False, True), tuple(x.payload["last"] for x in forwarded[1:]))

    def test_complete_w_burst_may_arrive_before_aw(self) -> None:
        system = self._system()
        session = system.open_session()
        data = session.step(
            session.initial_state(),
            self._manager_action(1, _w(0xA5A5A5A5, last=True)),
        )
        self.assertEqual((), self._captured(data.state, "target1"))

        address = session.step(
            data.state, self._manager_action(1, _aw(5, 0x2000))
        )
        forwarded = self._captured(address.state, "target1")
        self.assertEqual(("AW", "W"), tuple(x.kind for x in forwarded))
        self.assertEqual(5, forwarded[0].key)

    def test_same_downstream_bid_returns_to_owners_in_acceptance_order(self) -> None:
        system = self._system()
        session = system.open_session()
        first = self._write(
            session, session.initial_state(), 0, 3, 0x3000, 0x10
        )
        second = self._write(session, first.state, 1, 3, 0x3004, 0x20)

        backend = system.virtual_duts["crossbar"].backend
        assert isinstance(backend, Axi4WriteCrossbarBackend)
        crossbar = second.state.dut_states["crossbar"]
        assert isinstance(crossbar, Axi4WriteCrossbarState)
        owners = backend.return_owner_queues(crossbar)[("m2", 3)]
        self.assertEqual(
            ("s0", "s1"), tuple(item.ingress_port for item in owners)
        )

        first_b = session.step(second.state, self._target_response(2, 3))
        second_b = session.step(first_b.state, self._target_response(2, 3))
        self.assertEqual(1, len(self._captured(second_b.state, "manager0")))
        self.assertEqual(1, len(self._captured(second_b.state, "manager1")))
        self.assertTrue(session.is_quiescent(second_b.state))

    def test_same_ingress_bid_waits_before_changing_destination(self) -> None:
        system = self._system()
        session = system.open_session()
        first = self._write(
            session, session.initial_state(), 0, 1, 0x1000, 0x11
        )
        blocked = session.step(
            first.state, self._manager_action(0, _aw(1, 0x2000))
        )
        self.assertIsNotNone(blocked.blocked)
        assert blocked.blocked is not None
        self.assertEqual(
            "crossbar.axi4_write_id_destination", blocked.blocked.resource
        )
        self.assertIs(blocked.state, first.state)

        completed = session.step(first.state, self._target_response(0, 1))
        retried_aw = session.step(
            completed.state, self._manager_action(0, _aw(1, 0x2000))
        )
        retried = session.step(
            retried_aw.state, self._manager_action(0, _w(0x22, last=True))
        )
        self.assertIsNone(retried.blocked)
        self.assertEqual(
            ("AW", "W"),
            tuple(x.kind for x in self._captured(retried.state, "target1")),
        )
        self.assertEqual(
            1,
            len(self._captured(completed.state, "manager0")),
        )

    def test_same_bid_on_different_ingresses_and_targets_is_independent(self) -> None:
        system = self._system()
        session = system.open_session()
        first = self._write(
            session, session.initial_state(), 0, 2, 0x1000, 0x11
        )
        second = self._write(session, first.state, 1, 2, 0x4000, 0x44)

        later_first = session.step(second.state, self._target_response(3, 2))
        earlier_second = session.step(
            later_first.state, self._target_response(0, 2)
        )
        self.assertEqual(1, len(self._captured(earlier_second.state, "manager0")))
        self.assertEqual(1, len(self._captured(earlier_second.state, "manager1")))
        self.assertTrue(session.is_quiescent(earlier_second.state))

    def test_decode_miss_consumes_complete_w_before_local_decerr(self) -> None:
        system = self._system()
        session = system.open_session()
        address = session.step(
            session.initial_state(),
            self._manager_action(0, _aw(4, 0x5000, length=1)),
        )
        first_data = session.step(
            address.state,
            self._manager_action(0, _w(0x11, last=False)),
        )
        self.assertEqual((), self._captured(first_data.state, "manager0"))
        final_data = session.step(
            first_data.state,
            self._manager_action(0, _w(0x22, last=True)),
        )
        response = self._captured(final_data.state, "manager0")
        self.assertEqual(1, len(response))
        self.assertEqual(("B", "DECERR"), (response[0].kind, response[0].payload["resp"]))
        self.assertTrue(
            all(not self._captured(final_data.state, f"target{i}") for i in range(4))
        )
        self.assertTrue(session.is_quiescent(final_data.state))

    def test_table_capacity_blocks_aw_admission_atomically(self) -> None:
        system = self._system(
            table_profile=Axi4WriteRouteTableProfile(
                active_id_capacity=1,
                outstanding_bursts_per_id=1,
            )
        )
        session = system.open_session()
        first = self._write(
            session, session.initial_state(), 0, 1, 0x1000, 0x11
        )
        blocked = session.step(
            first.state, self._manager_action(0, _aw(2, 0x2000))
        )
        self.assertIsNotNone(blocked.blocked)
        assert blocked.blocked is not None
        self.assertEqual("crossbar.axi4_write_route_table", blocked.blocked.resource)
        self.assertIs(blocked.state, first.state)

        completed = session.step(first.state, self._target_response(0, 1))
        retried_aw = session.step(
            completed.state, self._manager_action(0, _aw(2, 0x2000))
        )
        retried = session.step(
            retried_aw.state, self._manager_action(0, _w(0x22, last=True))
        )
        self.assertIsNone(retried.blocked)

    def test_aw_and_pre_aw_w_storage_have_independent_capacity(self) -> None:
        profile = Axi4BurstAssemblyProfile(
            max_pending_aw=1,
            max_pre_aw_w_bursts=1,
            max_buffered_w_beats=2,
        )
        system = self._system(assembly_profile=profile)
        session = system.open_session()

        first_aw = session.step(
            session.initial_state(), self._manager_action(0, _aw(1, 0x1000))
        )
        aw_blocked = session.step(
            first_aw.state, self._manager_action(0, _aw(2, 0x2000))
        )
        self.assertIsNotNone(aw_blocked.blocked)
        assert aw_blocked.blocked is not None
        self.assertEqual(
            "crossbar.axi4_write_pending_aw", aw_blocked.blocked.resource
        )
        self.assertIs(aw_blocked.state, first_aw.state)

        first_w = session.step(
            session.initial_state(),
            self._manager_action(1, _w(0x11, last=True)),
        )
        w_blocked = session.step(
            first_w.state, self._manager_action(1, _w(0x22, last=True))
        )
        self.assertIsNotNone(w_blocked.blocked)
        assert w_blocked.blocked is not None
        self.assertEqual(
            "crossbar.axi4_write_pre_aw_w_bursts", w_blocked.blocked.resource
        )
        self.assertIs(w_blocked.state, first_w.state)

    def test_backend_rejects_orphan_b_exclusive_aw_and_full_profile(self) -> None:
        system = self._system()
        backend = system.virtual_duts["crossbar"].backend
        assert isinstance(backend, Axi4WriteCrossbarBackend)
        state = backend.initial_state()

        orphan = backend.accept(state, PortInput("m0", _b(1)))
        self.assertIsNotNone(orphan.fault)
        assert orphan.fault is not None
        self.assertEqual("axi4_write_crossbar.orphan_response", orphan.fault.rule)

        exclusive = backend.accept(
            state, PortInput("s0", _aw(1, 0x1000, lock=1))
        )
        self.assertIsNotNone(exclusive.fault)
        assert exclusive.fault is not None
        self.assertEqual("axi4_write_crossbar.exclusive", exclusive.fault.rule)

        with self.assertRaisesRegex(ValueError, "requires an AW/W/B-only interface"):
            build_axi4_write_crossbar_vdut(
                "full_crossbar",
                build_axi4_interface(Axi4Config(data_width=32, id_width=3)),
                ("s0",),
                ("m0",),
                (AddressRoute("target", 0x1000, TARGET_BYTES, "m0", 0),),
            )


if __name__ == "__main__":
    unittest.main()
