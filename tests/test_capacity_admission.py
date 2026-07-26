from __future__ import annotations

import unittest

from protocol_model.interface import InterfaceEventKind, InterfaceProtocol
from protocol_model.semantics import EventSchema
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    ResourceDemand,
    SemanticComponent,
    SemanticFragment,
    SemanticStep,
)
from protocol_model.system import SystemAction, SystemProtocol, VirtualDutPortRef
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import InterfacePort


class _BlockingLinkMonitor(SemanticComponent):
    name = "admission"

    def initial_state(self) -> int:
        return 0

    def observes(self, _event: CanonicalEvent) -> bool:
        return True

    def is_quiescent(self, _state: int) -> bool:
        return True

    def step(self, state: int, _event: CanonicalEvent) -> SemanticStep:
        return SemanticStep(
            state,
            blocked=ResourceDemand(
                "slot",
                ConstraintScope.INTERFACE,
                available=0,
                capacity=1,
                reason="test link admission is closed",
            ),
        )


def _blocking_protocol() -> InterfaceProtocol:
    event = EventSchema("PING")
    channel = InterfaceEventKind("ping", "source", "sink", event)
    monitor = _BlockingLinkMonitor()
    return InterfaceProtocol.define(
        "blocking_link",
        roles=frozenset(("source", "sink")),
        event_kinds={channel.name: channel},
        fragments=(SemanticFragment.empty("blocking_link.base"),),
        monitors={monitor.name: monitor},
    )


class CapacityAdmissionTest(unittest.TestCase):
    def test_link_block_propagates_without_committing_system_state(self) -> None:
        protocol = _blocking_protocol()
        source = VirtualDut(
            "source",
            {"bus": InterfacePort("bus", protocol, "source")},
        )
        sink = VirtualDut(
            "sink",
            {"bus": InterfacePort("bus", protocol, "sink")},
        )
        system = SystemProtocol.from_interface(
            "blocked_system",
            connection_name="bus",
            protocol=protocol,
            endpoints={
                "source": (source, "bus"),
                "sink": (sink, "bus"),
            },
        )
        session = system.open_session()
        initial = session.initial_state()

        blocked = session.step(
            initial,
            SystemAction(
                VirtualDutPortRef("source", "bus"),
                CanonicalEvent("PING"),
            ),
        )

        self.assertIsNone(blocked.fault)
        self.assertIs(blocked.state, initial)
        self.assertEqual((), blocked.emissions)
        self.assertIsNotNone(blocked.blocked)
        assert blocked.blocked is not None
        self.assertEqual("interface.bus.slot", blocked.blocked.resource)
        self.assertEqual("bus.admission", blocked.blocked.location)


if __name__ == "__main__":
    unittest.main()
