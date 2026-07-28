from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.endpoints.queued import (
    build_amba_queued_address_responder_vdut,
)
from protocol_model.integrations.recipes.amba.fabrics import (
    build_axi4_lite_address_crossbar_vdut,
)
from protocol_model.protocols.amba.axi.axi4_lite import build_axi4_lite_interface
from protocol_model.semantics import (
    CanonicalEvent,
    ResourceExhaustionPolicy,
)
from protocol_model.system import (
    AddressClaim,
    AddressRouterContract,
    AddressWindow,
    DutAdvanceAction,
    SystemAction,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.address.memory import MemoryRegion
from protocol_model.virtual_dut.address.space import AddressSpace
from protocol_model.virtual_dut.backend.queued_address import (
    constant_address_delay,
)
from protocol_model.virtual_dut.backend.simple import CaptureBackend, CaptureState
from protocol_model.virtual_dut.backend.transition import PortInput
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import InterfacePort
from protocol_model.virtual_dut.fabric import (
    AddressRoute,
    ScheduledAddressCrossbarState,
)
from protocol_model.virtual_dut.fabric.crossbar_state import (
    QueuedIngressErrorCompletion,
)


class Axi4LiteCrossbarTest(unittest.TestCase):
    @staticmethod
    def _manager(name, protocol) -> VirtualDut:
        return VirtualDut(
            name,
            {"axi": InterfacePort("axi", protocol, "manager")},
            backend=CaptureBackend(),
        )

    @staticmethod
    def _target(name, protocol, fill: int) -> VirtualDut:
        return build_amba_queued_address_responder_vdut(
            name,
            protocol,
            AddressSpace(
                (
                    MemoryRegion(
                        f"{name}_memory",
                        0x100,
                        initial_content=bytes((fill,)) * 0x10,
                    ),
                )
            ),
            capacity=2,
            delay_policy=constant_address_delay(0),
            port_name="axi",
        )

    def _system(
        self,
        *,
        ingress_queue_capacity: int = 2,
        exhaustion_policy: ResourceExhaustionPolicy | str = (
            ResourceExhaustionPolicy.BLOCK
        ),
    ):
        protocol = build_axi4_lite_interface()
        manager0 = self._manager("manager0", protocol)
        manager1 = self._manager("manager1", protocol)
        target0 = self._target("target0", protocol, 0x11)
        target1 = self._target("target1", protocol, 0x22)
        routes = (
            AddressRoute(
                "target0",
                0x1000,
                0x100,
                "m_target0",
                output_base_address=0,
            ),
            AddressRoute(
                "target1",
                0x2000,
                0x100,
                "m_target1",
                output_base_address=0,
            ),
        )
        router = AddressRouterContract(
            "main_crossbar",
            "crossbar",
            ("s_manager0", "s_manager1"),
            ("m_target0", "m_target1"),
            routes,
        )
        builder = SystemProtocolBuilder("two_by_two_axi4_lite")
        for dut in (manager0, manager1, target0, target1):
            builder.add_dut(dut)
        builder.construct_address_router(
            router,
            lambda contract: build_axi4_lite_address_crossbar_vdut(
                contract.router,
                protocol,
                contract.ingress_ports,
                contract.egress_ports,
                contract.routes,
                ingress_queue_capacity=ingress_queue_capacity,
                exhaustion_policy=exhaustion_policy,
            ),
        )
        builder.connect(
            "manager0_bus",
            protocol,
            {
                "manager": VirtualDutPortRef("manager0", "axi"),
                "subordinate": VirtualDutPortRef(
                    "crossbar", "s_manager0"
                ),
            },
        )
        builder.connect(
            "manager1_bus",
            protocol,
            {
                "manager": VirtualDutPortRef("manager1", "axi"),
                "subordinate": VirtualDutPortRef(
                    "crossbar", "s_manager1"
                ),
            },
        )
        builder.connect(
            "target0_bus",
            protocol,
            {
                "manager": VirtualDutPortRef("crossbar", "m_target0"),
                "subordinate": VirtualDutPortRef("target0", "axi"),
            },
        )
        builder.connect(
            "target1_bus",
            protocol,
            {
                "manager": VirtualDutPortRef("crossbar", "m_target1"),
                "subordinate": VirtualDutPortRef("target1", "axi"),
            },
        )
        builder.add_address_claim(
            AddressClaim(
                "target0_local",
                VirtualDutPortRef("target0", "axi"),
                AddressWindow(0, 0x100),
            )
        )
        builder.add_address_claim(
            AddressClaim(
                "target1_local",
                VirtualDutPortRef("target1", "axi"),
                AddressWindow(0, 0x100),
            )
        )
        return builder.build()

    def test_full_ingress_blocks_and_system_step_rolls_back_for_retry(self) -> None:
        system = self._system(ingress_queue_capacity=1)
        session = system.open_session()
        first = session.step(
            session.initial_state(), self._read("manager0", 0x1000)
        )
        blocked = session.step(
            first.state, self._read("manager0", 0x1004)
        )

        self.assertIsNone(blocked.fault)
        self.assertIsNotNone(blocked.blocked)
        assert blocked.blocked is not None
        self.assertEqual(
            "crossbar.ingress_request_fifo", blocked.blocked.resource
        )
        self.assertEqual("crossbar.s_manager0", blocked.blocked.location)
        self.assertEqual((), blocked.emissions)
        self.assertIs(blocked.state, first.state)
        self.assertEqual(first.state.events, blocked.state.events)
        self.assertEqual(
            first.state.connection_states["manager0_bus"],
            blocked.state.connection_states["manager0_bus"],
        )

        granted = session.step(
            blocked.state, DutAdvanceAction("crossbar")
        )
        retried = session.step(
            granted.state, self._read("manager0", 0x1004)
        )
        self.assertIsNone(retried.fault)
        self.assertIsNone(retried.blocked)
        crossbar_state = retried.state.dut_states["crossbar"]
        assert isinstance(crossbar_state, ScheduledAddressCrossbarState)
        self.assertEqual(1, len(crossbar_state.ingress_queues["s_manager0"]))

    def test_crossbar_exhaustion_policy_can_complete_error_or_fault(self) -> None:
        error_system = self._system(
            ingress_queue_capacity=1,
            exhaustion_policy=ResourceExhaustionPolicy.ERROR_COMPLETION,
        )
        session = error_system.open_session()
        first = session.step(
            session.initial_state(), self._read("manager0", 0x1000)
        )
        overflow = session.step(
            first.state, self._read("manager0", 0x1004)
        )

        self.assertIsNone(overflow.blocked)
        self.assertIsNone(overflow.fault)
        self.assertEqual(("AR",), tuple(
            item.event.kind for item in overflow.emissions
        ))
        crossbar_state = overflow.state.dut_states["crossbar"]
        assert isinstance(crossbar_state, ScheduledAddressCrossbarState)
        self.assertEqual(2, len(crossbar_state.ingress_queues["s_manager0"]))
        self.assertIsInstance(
            crossbar_state.ingress_queues["s_manager0"][1],
            QueuedIngressErrorCompletion,
        )

        blocked = session.step(
            overflow.state, self._read("manager0", 0x1008)
        )
        self.assertIsNotNone(blocked.blocked)
        assert blocked.blocked is not None
        self.assertEqual(
            "crossbar.ingress_error_completion_slot",
            blocked.blocked.resource,
        )
        self.assertIs(blocked.state, overflow.state)

        forwarded = session.step(
            overflow.state, DutAdvanceAction("crossbar")
        )
        succeeded = session.step(
            forwarded.state, DutAdvanceAction("target0")
        )
        upstream_success = tuple(
            item
            for item in succeeded.emissions
            if item.connection == "manager0_bus" and item.event.kind == "R"
        )
        self.assertEqual(1, len(upstream_success))
        self.assertEqual("OKAY", upstream_success[0].event.payload["resp"])

        errored = session.step(
            succeeded.state, DutAdvanceAction("crossbar")
        )
        self.assertEqual(("R",), tuple(
            item.event.kind for item in errored.emissions
        ))
        self.assertEqual("SLVERR", errored.emissions[0].event.payload["resp"])

        trace = session.trace(errored.state)
        self.assertIn(0, trace.predecessors(upstream_success[0].index))
        self.assertEqual(
            (1,), trace.predecessors(errored.emissions[0].index)
        )

        fault_system = self._system(
            ingress_queue_capacity=1,
            exhaustion_policy=ResourceExhaustionPolicy.FAULT,
        )
        fault_backend = fault_system.virtual_duts["crossbar"].backend
        assert fault_backend is not None
        accepted = fault_backend.accept(
            fault_backend.initial_state(),
            PortInput(
                "s_manager0",
                CanonicalEvent("AR", None, {"addr": 0x1000, "prot": 0}),
            ),
        )
        faulted = fault_backend.accept(
            accepted.state,
            PortInput(
                "s_manager0",
                CanonicalEvent("AR", None, {"addr": 0x1004, "prot": 0}),
            ),
        )
        self.assertIs(faulted.state, accepted.state)
        self.assertIsNone(faulted.blocked)
        self.assertEqual("address_crossbar.capacity", faulted.fault.rule)

    @staticmethod
    def _read(manager: str, address: int) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef(manager, "axi"),
            CanonicalEvent("AR", None, {"addr": address, "prot": 0}),
        )

    @staticmethod
    def _write_address(manager: str, address: int) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef(manager, "axi"),
            CanonicalEvent("AW", None, {"addr": address, "prot": 0}),
        )

    @staticmethod
    def _write_data(manager: str, data: int) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef(manager, "axi"),
            CanonicalEvent("W", None, {"data": data, "strb": 0b1111}),
        )

    @staticmethod
    def _captured(state, manager: str) -> tuple[CanonicalEvent, ...]:
        captured = state.dut_states[manager]
        assert isinstance(captured, CaptureState)
        return tuple(item.event for item in captured.received)

    def test_resolves_four_paths_and_grants_distinct_egresses_together(self) -> None:
        system = self._system()
        elaborated = system.elaborate()
        assert elaborated.address_plan is not None
        self.assertEqual(4, len(elaborated.address_plan.paths))

        session = system.open_session()
        first = session.step(
            session.initial_state(), self._read("manager0", 0x1000)
        )
        second = session.step(
            first.state, self._read("manager1", 0x2000)
        )
        granted = session.step(second.state, DutAdvanceAction("crossbar"))

        for transition in (first, second, granted):
            self.assertIsNone(transition.fault)
        self.assertEqual(
            ("target0_bus", "target1_bus"),
            tuple(item.connection for item in granted.emissions),
        )
        crossbar_state = granted.state.dut_states["crossbar"]
        self.assertIsInstance(crossbar_state, ScheduledAddressCrossbarState)
        self.assertEqual(2, len(crossbar_state.pending))

        target1_done = session.step(
            granted.state, DutAdvanceAction("target1")
        )
        target0_done = session.step(
            target1_done.state, DutAdvanceAction("target0")
        )
        self.assertEqual(
            ("target1_bus", "manager1_bus"),
            tuple(item.connection for item in target1_done.emissions),
        )
        self.assertEqual(
            ("target0_bus", "manager0_bus"),
            tuple(item.connection for item in target0_done.emissions),
        )
        self.assertEqual(
            0x11111111,
            self._captured(target0_done.state, "manager0")[0].payload["data"],
        )
        self.assertEqual(
            0x22222222,
            self._captured(target0_done.state, "manager1")[0].payload["data"],
        )
        self.assertTrue(session.is_quiescent(target0_done.state))

    def test_shared_egress_holds_one_owner_and_returns_to_each_ingress(self) -> None:
        system = self._system()
        session = system.open_session()
        first = session.step(
            session.initial_state(), self._read("manager0", 0x1000)
        )
        second = session.step(
            first.state, self._read("manager1", 0x1004)
        )
        first_grant = session.step(
            second.state, DutAdvanceAction("crossbar")
        )
        blocked = session.step(
            first_grant.state, DutAdvanceAction("crossbar")
        )

        self.assertEqual(("target0_bus",), tuple(
            item.connection for item in first_grant.emissions
        ))
        self.assertEqual((), blocked.emissions)
        state = first_grant.state.dut_states["crossbar"]
        assert isinstance(state, ScheduledAddressCrossbarState)
        owner = next(iter(state.pending.values()))
        self.assertEqual("s_manager0", owner.ingress_port)
        self.assertEqual("m_target0", owner.egress_port)

        first_done = session.step(
            blocked.state, DutAdvanceAction("target0")
        )
        second_grant = session.step(
            first_done.state, DutAdvanceAction("crossbar")
        )
        second_done = session.step(
            second_grant.state, DutAdvanceAction("target0")
        )

        self.assertEqual(
            ("target0_bus", "manager0_bus"),
            tuple(item.connection for item in first_done.emissions),
        )
        self.assertEqual(
            ("target0_bus",),
            tuple(item.connection for item in second_grant.emissions),
        )
        self.assertEqual(
            ("target0_bus", "manager1_bus"),
            tuple(item.connection for item in second_done.emissions),
        )
        self.assertEqual(1, len(self._captured(second_done.state, "manager0")))
        self.assertEqual(1, len(self._captured(second_done.state, "manager1")))
        self.assertTrue(session.is_quiescent(second_done.state))

    def test_ingress_order_holds_miss_and_write_fragments_are_isolated(self) -> None:
        system = self._system()
        session = system.open_session()
        mapped = session.step(
            session.initial_state(), self._read("manager0", 0x1000)
        )
        missed = session.step(
            mapped.state, self._read("manager0", 0x3000)
        )
        granted = session.step(missed.state, DutAdvanceAction("crossbar"))
        held = session.step(granted.state, DutAdvanceAction("crossbar"))

        self.assertEqual(("target0_bus",), tuple(
            item.connection for item in granted.emissions
        ))
        self.assertEqual((), held.emissions)
        mapped_done = session.step(
            held.state, DutAdvanceAction("target0")
        )
        miss_done = session.step(
            mapped_done.state, DutAdvanceAction("crossbar")
        )
        self.assertEqual(
            ("manager0_bus",), tuple(item.connection for item in miss_done.emissions)
        )
        self.assertEqual("DECERR", miss_done.emissions[0].event.payload["resp"])

        fresh = session.initial_state()
        m0_data = session.step(fresh, self._write_data("manager0", 0xAABBCCDD))
        m1_address = session.step(
            m0_data.state, self._write_address("manager1", 0x2000)
        )
        partial = m1_address.state.dut_states["crossbar"]
        assert isinstance(partial, ScheduledAddressCrossbarState)
        self.assertEqual((), partial.ingress_queues["s_manager0"])
        self.assertEqual((), partial.ingress_queues["s_manager1"])

        m0_address = session.step(
            m1_address.state, self._write_address("manager0", 0x1000)
        )
        m1_data = session.step(
            m0_address.state, self._write_data("manager1", 0x11223344)
        )
        joined = m1_data.state.dut_states["crossbar"]
        assert isinstance(joined, ScheduledAddressCrossbarState)
        self.assertEqual(1, len(joined.ingress_queues["s_manager0"]))
        self.assertEqual(1, len(joined.ingress_queues["s_manager1"]))

        writes_granted = session.step(
            m1_data.state, DutAdvanceAction("crossbar")
        )
        target0_done = session.step(
            writes_granted.state, DutAdvanceAction("target0")
        )
        target1_done = session.step(
            target0_done.state, DutAdvanceAction("target1")
        )
        self.assertIsNone(target1_done.fault)
        self.assertEqual(
            ("B",),
            tuple(event.kind for event in self._captured(
                target1_done.state, "manager0"
            )),
        )
        self.assertEqual(
            ("B",),
            tuple(event.kind for event in self._captured(
                target1_done.state, "manager1"
            )),
        )
        self.assertTrue(session.is_quiescent(target1_done.state))


if __name__ == "__main__":
    unittest.main()
