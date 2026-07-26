from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.endpoints.queued import (
    build_amba_queued_address_responder_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints.empty import (
    build_apb_idle_source_vdut,
)
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface
from protocol_model.protocols.amba.axi.axi4_lite import build_axi4_lite_interface
from protocol_model.semantics import (
    CanonicalEvent,
    ResourceExhaustionPolicy,
)
from protocol_model.system import DutAdvanceAction, SystemAction, SystemProtocol
from protocol_model.virtual_dut.address.memory import MemoryRegion
from protocol_model.virtual_dut.address.space import AddressSpace
from protocol_model.virtual_dut.backend.queued_address import (
    QueuedAddressErrorCompletion,
    QueuedAddressPhase,
    QueuedAddressResponderBackend,
    constant_address_delay,
)
from protocol_model.virtual_dut.backend.simple import CaptureBackend
from protocol_model.virtual_dut.backend.transition import PortInput
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import InterfacePort


class QueuedAddressResponderTest(unittest.TestCase):
    @staticmethod
    def _space() -> AddressSpace:
        return AddressSpace(
            (
                MemoryRegion(
                    "ram",
                    0x100,
                    base_address=0x1000,
                    initial_content=bytes.fromhex("1122334455667788"),
                ),
            )
        )

    @staticmethod
    def _read(address: int) -> PortInput:
        return PortInput(
            "bus",
            CanonicalEvent("AR", None, {"addr": address, "prot": 0}),
        )

    def test_fifo_delay_requires_explicit_advances_before_responses(self) -> None:
        protocol = build_axi4_lite_interface()

        def delay(_access, context):
            return 2 if context.request_serial == 0 else 1

        dut = build_amba_queued_address_responder_vdut(
            "memory",
            protocol,
            self._space(),
            capacity=2,
            delay_policy=delay,
        )
        backend = dut.backend
        self.assertIsInstance(backend, QueuedAddressResponderBackend)
        assert isinstance(backend, QueuedAddressResponderBackend)
        state = backend.initial_state()

        first = backend.accept(state, self._read(0x1000))
        second = backend.accept(first.state, self._read(0x1004))

        self.assertIsNone(first.fault)
        self.assertIsNone(second.fault)
        self.assertEqual((), first.emissions)
        self.assertEqual((), second.emissions)
        self.assertEqual((2, 2), backend.queue_usage(second.state))
        self.assertEqual(
            (QueuedAddressPhase.DELAYING, QueuedAddressPhase.DELAYING),
            tuple(item.phase for item in second.state.queue),
        )

        full = backend.accept(second.state, self._read(0x1008))
        self.assertIs(full.state, second.state)
        self.assertIsNone(full.fault)
        self.assertIsNotNone(full.blocked)
        assert full.blocked is not None
        self.assertEqual("request_fifo", full.blocked.resource)
        self.assertEqual(1, full.blocked.required)
        self.assertEqual(0, full.blocked.available)
        self.assertEqual(2, full.blocked.capacity)

        fragment = backend.accept(
            second.state,
            PortInput(
                "bus",
                CanonicalEvent(
                    "W", None, {"data": 0, "strb": 0b1111}
                ),
            ),
        )
        self.assertIsNone(fragment.fault)
        self.assertEqual(2, len(fragment.state.queue))

        aged = backend.advance(second.state)
        self.assertEqual((), aged.emissions)
        self.assertEqual(
            (QueuedAddressPhase.DELAYING, QueuedAddressPhase.READY),
            tuple(item.phase for item in aged.state.queue),
        )
        self.assertEqual(1, aged.state.advance_index)

        first_response = backend.advance(aged.state)
        self.assertEqual(("R",), tuple(
            item.event.kind for item in first_response.emissions
        ))
        self.assertEqual(
            0x44332211, first_response.emissions[0].event.payload["data"]
        )
        self.assertEqual(1, len(first_response.state.queue))

        second_response = backend.advance(first_response.state)
        self.assertEqual(
            0x88776655, second_response.emissions[0].event.payload["data"]
        )
        self.assertTrue(backend.is_quiescent(second_response.state))

    def test_exhaustion_policy_separates_error_completion_from_fault(self) -> None:
        protocol = build_axi4_lite_interface()
        error_dut = build_amba_queued_address_responder_vdut(
            "error_memory",
            protocol,
            self._space(),
            capacity=1,
            delay_policy=constant_address_delay(0),
            exhaustion_policy=ResourceExhaustionPolicy.ERROR_COMPLETION,
        )
        error_backend = error_dut.backend
        assert isinstance(error_backend, QueuedAddressResponderBackend)
        manager = VirtualDut(
            "manager",
            {"bus": InterfacePort("bus", protocol, "manager")},
            backend=CaptureBackend(),
        )
        system = SystemProtocol.from_interface(
            "ordered_overflow",
            connection_name="bus",
            protocol=protocol,
            endpoints={
                "manager": (manager, "bus"),
                "subordinate": (error_dut, "bus"),
            },
        )
        session = system.open_session()
        origin = system.connections["bus"].endpoints["manager"]
        first = session.step(
            session.initial_state(),
            SystemAction(
                origin,
                CanonicalEvent("AR", None, {"addr": 0x1000, "prot": 0}),
            ),
        )
        overflow = session.step(
            first.state,
            SystemAction(
                origin,
                CanonicalEvent("AR", None, {"addr": 0x1004, "prot": 0}),
            ),
        )

        self.assertIsNone(overflow.fault)
        self.assertIsNone(overflow.blocked)
        self.assertEqual(("AR",), tuple(
            item.event.kind for item in overflow.emissions
        ))
        queued_state = overflow.state.dut_states["error_memory"]
        self.assertEqual(2, len(queued_state.queue))
        self.assertIsInstance(
            queued_state.queue[1], QueuedAddressErrorCompletion
        )

        blocked = session.step(
            overflow.state,
            SystemAction(
                origin,
                CanonicalEvent("AR", None, {"addr": 0x1008, "prot": 0}),
            ),
        )
        self.assertIsNotNone(blocked.blocked)
        assert blocked.blocked is not None
        self.assertEqual(
            "error_memory.error_completion_slot", blocked.blocked.resource
        )
        self.assertIs(blocked.state, overflow.state)

        succeeded = session.step(
            overflow.state, DutAdvanceAction("error_memory")
        )
        errored = session.step(
            succeeded.state, DutAdvanceAction("error_memory")
        )
        self.assertEqual("OKAY", succeeded.emissions[0].event.payload["resp"])
        self.assertEqual("SLVERR", errored.emissions[0].event.payload["resp"])
        self.assertEqual((0,), session.trace(errored.state).predecessors(2))
        self.assertEqual((1,), session.trace(errored.state).predecessors(3))
        self.assertTrue(session.is_quiescent(errored.state))

        fault_dut = build_amba_queued_address_responder_vdut(
            "fault_memory",
            protocol,
            self._space(),
            capacity=1,
            delay_policy=constant_address_delay(0),
            exhaustion_policy=ResourceExhaustionPolicy.FAULT,
        )
        fault_backend = fault_dut.backend
        assert isinstance(fault_backend, QueuedAddressResponderBackend)
        accepted = fault_backend.accept(
            fault_backend.initial_state(), self._read(0x1000)
        )
        faulted = fault_backend.accept(accepted.state, self._read(0x1004))

        self.assertIs(faulted.state, accepted.state)
        self.assertIsNone(faulted.blocked)
        self.assertEqual(
            "queued_address_responder.capacity", faulted.fault.rule
        )

    def test_write_state_changes_only_at_the_service_advance(self) -> None:
        protocol = build_axi4_lite_interface()
        dut = build_amba_queued_address_responder_vdut(
            "memory",
            protocol,
            self._space(),
            capacity=2,
            delay_policy=constant_address_delay(0),
        )
        backend = dut.backend
        assert isinstance(backend, QueuedAddressResponderBackend)
        state = backend.initial_state()

        data = backend.accept(
            state,
            PortInput(
                "bus",
                CanonicalEvent(
                    "W",
                    None,
                    {"data": 0xAABBCCDD, "strb": 0b1111},
                ),
            ),
        )
        queued = backend.accept(
            data.state,
            PortInput(
                "bus",
                CanonicalEvent(
                    "AW", None, {"addr": 0x1000, "prot": 0}
                ),
            ),
        )

        self.assertEqual((), data.emissions)
        self.assertEqual((), queued.emissions)
        self.assertEqual(1, len(queued.state.queue))
        self.assertEqual(state.handler_state, queued.state.handler_state)

        written = backend.advance(queued.state)
        self.assertIsNone(written.fault)
        self.assertEqual(("B",), tuple(
            item.event.kind for item in written.emissions
        ))

        read = backend.accept(written.state, self._read(0x1000))
        read_response = backend.advance(read.state)
        self.assertEqual(
            0xAABBCCDD, read_response.emissions[0].event.payload["data"]
        )
        self.assertTrue(backend.is_quiescent(read_response.state))

    def test_invalid_delay_result_is_an_atomic_model_fault(self) -> None:
        dut = build_amba_queued_address_responder_vdut(
            "memory",
            build_axi4_lite_interface(),
            self._space(),
            capacity=1,
            delay_policy=lambda _access, _context: -1,
        )
        backend = dut.backend
        assert isinstance(backend, QueuedAddressResponderBackend)
        state = backend.initial_state()

        rejected = backend.accept(state, self._read(0x1000))

        self.assertIs(rejected.state, state)
        self.assertEqual((), rejected.emissions)
        self.assertEqual(
            "queued_address_responder.delay_policy", rejected.fault.rule
        )

    def test_system_advance_routes_a_delayed_apb_completion(self) -> None:
        protocol = build_apb4_interface()
        source = build_apb_idle_source_vdut("source", protocol)
        target = build_amba_queued_address_responder_vdut(
            "target",
            protocol,
            self._space(),
            capacity=2,
            delay_policy=constant_address_delay(2),
            port_name="apb",
        )
        system = SystemProtocol.from_interface(
            "delayed_apb",
            connection_name="bus",
            protocol=protocol,
            endpoints={
                "requester": (source, "apb"),
                "completer": (target, "apb"),
            },
        )
        session = system.open_session()
        requested = session.step(
            session.initial_state(),
            SystemAction(
                system.connections["bus"].endpoints["requester"],
                CanonicalEvent(
                    "READ", None, {"addr": 0x1000, "prot": 0}
                ),
            ),
        )

        self.assertIsNone(requested.fault)
        self.assertEqual(
            ("READ",), tuple(item.event.kind for item in requested.emissions)
        )
        self.assertFalse(session.is_quiescent(requested.state))

        waiting = session.step(requested.state, DutAdvanceAction("target"))
        self.assertIsNone(waiting.fault)
        self.assertEqual((), waiting.emissions)

        completed = session.step(waiting.state, DutAdvanceAction("target"))
        self.assertIsNone(completed.fault)
        self.assertEqual(
            ("READ_RESPONSE",),
            tuple(item.event.kind for item in completed.emissions),
        )
        self.assertEqual(0x44332211, completed.emissions[0].event.payload["data"])
        self.assertEqual(((0, 1),), completed.state.causal_edges)
        self.assertTrue(session.is_quiescent(completed.state))


if __name__ == "__main__":
    unittest.main()
