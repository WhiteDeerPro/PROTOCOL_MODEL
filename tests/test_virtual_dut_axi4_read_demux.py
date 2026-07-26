from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.endpoints import (
    build_axi4_address_space_vdut,
)
from protocol_model.integrations.recipes.amba.fabrics import (
    Axi4ReadRouteTableProfile,
    build_axi4_read_demux_vdut,
)
from protocol_model.integrations.backends.amba.axi.axi4.read import (
    Axi4ReadCrossbarState,
)
from protocol_model.protocols.amba.axi.axi4 import (
    Axi4Config,
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
    PortInput,
    SteppedEmissionProfile,
    VirtualDut,
)


def _ar(read_id: int, address: int, *, length: int = 0) -> CanonicalEvent:
    return CanonicalEvent(
        "AR",
        read_id,
        {
            "addr": address,
            "len": length,
            "size": 2,
            "burst": "INCR",
            "lock": 0,
            "cache": 0,
            "prot": 0,
            "qos": 0,
            "region": 0,
        },
    )


def _r(read_id: int, data: int, *, last: bool) -> CanonicalEvent:
    return CanonicalEvent(
        "R",
        read_id,
        {"data": data, "resp": "OKAY", "last": last},
    )


class Axi4ReadDemuxTest(unittest.TestCase):
    def _system(
        self,
        *,
        table_profile: Axi4ReadRouteTableProfile | None = None,
    ):
        protocol = build_axi4_read_only_profile(
            Axi4Config(data_width=32, id_width=3)
        )
        manager = VirtualDut(
            "manager",
            {"axi": InterfacePort("axi", protocol, "manager")},
            backend=CaptureBackend(),
        )
        target0 = build_axi4_address_space_vdut(
            "target0",
            protocol,
            AddressSpace(
                (
                    MemoryRegion(
                        "target0_ram",
                        0x100,
                        initial_content=bytes.fromhex(
                            "11000000120000001300000014000000"
                        ),
                    ),
                )
            ),
            response_profile=SteppedEmissionProfile(capacity_events=16),
        )
        target1 = build_axi4_address_space_vdut(
            "target1",
            protocol,
            AddressSpace(
                (
                    MemoryRegion(
                        "target1_ram",
                        0x100,
                        initial_content=bytes.fromhex(
                            "21000000220000002300000024000000"
                        ),
                    ),
                )
            ),
            response_profile=SteppedEmissionProfile(capacity_events=16),
        )
        routes = (
            AddressRoute("target0", 0x1000, 0x100, "m0", 0),
            AddressRoute("target1", 0x2000, 0x100, "m1", 0),
        )
        contract = AddressRouterContract(
            "main_map",
            "demux",
            ("s_axi",),
            ("m0", "m1"),
            routes,
        )
        builder = SystemProtocolBuilder("axi4_read_demux_system")
        for dut in (manager, target0, target1):
            builder.add_dut(dut)
        builder.construct_address_router(
            contract,
            lambda received: build_axi4_read_demux_vdut(
                received.router,
                protocol,
                received.egress_ports,
                received.routes,
                ingress_port=received.ingress_ports[0],
                table_profile=table_profile,
            ),
        )
        builder.connect(
            "manager_bus",
            protocol,
            {
                "manager": VirtualDutPortRef("manager", "axi"),
                "subordinate": VirtualDutPortRef("demux", "s_axi"),
            },
        )
        for index in range(2):
            builder.connect(
                f"target{index}_bus",
                protocol,
                {
                    "manager": VirtualDutPortRef("demux", f"m{index}"),
                    "subordinate": VirtualDutPortRef(
                        f"target{index}", "axi"
                    ),
                },
            )
            builder.add_address_claim(
                AddressClaim(
                    f"target{index}_local",
                    VirtualDutPortRef(f"target{index}", "axi"),
                    AddressWindow(0, 0x100),
                )
            )
        return builder.build()

    @staticmethod
    def _issue(manager_address: int, read_id: int, *, length: int = 0):
        return SystemAction(
            VirtualDutPortRef("manager", "axi"),
            _ar(read_id, manager_address, length=length),
        )

    @staticmethod
    def _manager_responses(step) -> tuple[CanonicalEvent, ...]:
        return tuple(
            item.event
            for item in step.emissions
            if item.connection == "manager_bus" and item.event.kind == "R"
        )

    def test_different_ids_can_return_from_different_devices(self) -> None:
        system = self._system()
        session = system.open_session()
        first = session.step(
            session.initial_state(),
            self._issue(0x1000, 1, length=1),
        )
        second = session.step(
            first.state,
            self._issue(0x2000, 2, length=1),
        )

        pending = second.state.dut_states["demux"].pending
        by_id = {item.upstream_id: item for item in pending}
        self.assertEqual({1, 2}, set(by_id))
        self.assertEqual("m0", by_id[1].egress_port)
        self.assertEqual("m1", by_id[2].egress_port)
        self.assertEqual(2, by_id[1].remaining_beats)
        self.assertEqual(2, by_id[2].remaining_beats)

        target1_first = session.step(
            second.state, DutAdvanceAction("target1")
        )
        target1_last = session.step(
            target1_first.state, DutAdvanceAction("target1")
        )
        target0_first = session.step(
            target1_last.state, DutAdvanceAction("target0")
        )
        target0_last = session.step(
            target0_first.state, DutAdvanceAction("target0")
        )

        responses = tuple(
            self._manager_responses(step)[0]
            for step in (
                target1_first,
                target1_last,
                target0_first,
                target0_last,
            )
        )
        self.assertEqual((2, 2, 1, 1), tuple(item.key for item in responses))
        self.assertEqual((0x21, 0x22, 0x11, 0x12), tuple(
            item.payload["data"] for item in responses
        ))
        self.assertEqual((False, True, False, True), tuple(
            item.payload["last"] for item in responses
        ))
        self.assertEqual((), target0_last.state.dut_states["demux"].pending)

    def test_same_id_to_another_device_blocks_until_prior_rlast(self) -> None:
        system = self._system()
        session = system.open_session()
        first = session.step(
            session.initial_state(),
            self._issue(0x1000, 3, length=1),
        )
        blocked = session.step(first.state, self._issue(0x2000, 3))

        self.assertIsNone(blocked.fault)
        self.assertIsNotNone(blocked.blocked)
        assert blocked.blocked is not None
        self.assertEqual(
            "demux.axi4_read_id_destination", blocked.blocked.resource
        )
        self.assertIs(blocked.state, first.state)

        first_beat = session.step(
            first.state, DutAdvanceAction("target0")
        )
        still_owned = first_beat.state.dut_states["demux"].pending[0]
        self.assertEqual(1, still_owned.remaining_beats)
        last_beat = session.step(
            first_beat.state, DutAdvanceAction("target0")
        )
        self.assertEqual((), last_beat.state.dut_states["demux"].pending)

        retried = session.step(last_beat.state, self._issue(0x2000, 3))
        self.assertIsNone(retried.blocked)
        self.assertEqual(
            "m1", retried.state.dut_states["demux"].pending[0].egress_port
        )

    def test_same_id_same_device_queues_burst_metadata(self) -> None:
        system = self._system()
        session = system.open_session()
        first = session.step(
            session.initial_state(), self._issue(0x1000, 4)
        )
        second = session.step(first.state, self._issue(0x1004, 4))

        entries = second.state.dut_states["demux"].pending
        self.assertEqual((1, 1), tuple(
            item.remaining_beats for item in entries
        ))

        first_response = session.step(
            second.state, DutAdvanceAction("target0")
        )
        entries = first_response.state.dut_states["demux"].pending
        self.assertEqual((1,), tuple(
            item.remaining_beats for item in entries
        ))
        second_response = session.step(
            first_response.state, DutAdvanceAction("target0")
        )
        self.assertEqual((), second_response.state.dut_states["demux"].pending)
        self.assertEqual(0x11, self._manager_responses(first_response)[0].payload["data"])
        self.assertEqual(0x12, self._manager_responses(second_response)[0].payload["data"])

    def test_burst_crossing_route_window_returns_ordered_decerr(self) -> None:
        system = self._system()
        session = system.open_session()
        result = session.step(
            session.initial_state(),
            self._issue(0x10FC, 5, length=1),
        )

        responses = self._manager_responses(result)
        self.assertEqual(2, len(responses))
        self.assertEqual(("DECERR", "DECERR"), tuple(
            item.payload["resp"] for item in responses
        ))
        self.assertEqual((False, True), tuple(
            item.payload["last"] for item in responses
        ))
        self.assertEqual((), result.state.dut_states["demux"].pending)

    def test_route_table_capacity_blocks_and_rlast_releases_slot(self) -> None:
        system = self._system(
            table_profile=Axi4ReadRouteTableProfile(
                active_id_capacity=1,
                outstanding_bursts_per_id=2,
            )
        )
        session = system.open_session()
        first = session.step(
            session.initial_state(), self._issue(0x1000, 1)
        )
        blocked = session.step(first.state, self._issue(0x2000, 2))

        self.assertIsNotNone(blocked.blocked)
        assert blocked.blocked is not None
        self.assertEqual("demux.axi4_read_route_table", blocked.blocked.resource)
        completed = session.step(
            first.state, DutAdvanceAction("target0")
        )
        retried = session.step(completed.state, self._issue(0x2000, 2))
        self.assertIsNone(retried.blocked)

    def test_direct_backend_detects_early_rlast(self) -> None:
        system = self._system()
        backend = system.virtual_duts["demux"].backend
        assert backend is not None
        accepted = backend.accept(
            backend.initial_state(),
            PortInput("s_axi", _ar(6, 0x1000, length=1)),
        )
        self.assertIsInstance(accepted.state, Axi4ReadCrossbarState)
        faulted = backend.accept(
            accepted.state,
            PortInput("m0", _r(6, 0x11, last=True)),
        )

        self.assertIs(faulted.state, accepted.state)
        self.assertEqual("axi4_read_crossbar.response_last", faulted.fault.rule)

    def test_owner_table_rejects_response_from_wrong_device(self) -> None:
        system = self._system()
        backend = system.virtual_duts["demux"].backend
        assert backend is not None
        accepted = backend.accept(
            backend.initial_state(),
            PortInput("s_axi", _ar(7, 0x1000)),
        )
        faulted = backend.accept(
            accepted.state,
            PortInput("m1", _r(7, 0x21, last=True)),
        )

        self.assertIs(faulted.state, accepted.state)
        self.assertEqual(
            "axi4_read_crossbar.orphan_response", faulted.fault.rule
        )


if __name__ == "__main__":
    unittest.main()
