from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.control.interrupt import (
    build_edge_interrupt_controller_vdut,
    build_edge_interrupt_target_vdut,
)
from protocol_model.protocols.control.interrupt import (
    InterruptNotificationConfig,
    build_interrupt_notification_interface,
)
from protocol_model.semantics import (
    CanonicalEvent,
    ResourceExhaustionPolicy,
)
from protocol_model.system.protocol import SystemProtocol
from protocol_model.system.session import DutAdvanceAction, SystemAction
from protocol_model.system.topology.model import (
    InterfaceConnection,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.backend.interrupt import (
    InterruptControllerState,
    InterruptTargetState,
    PriorityInterruptControllerBackend,
)
from protocol_model.virtual_dut.backend.simple import CaptureBackend, CaptureState
from protocol_model.virtual_dut.backend.transition import PortInput
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import InterfacePort


def _notify(reference: int, interrupt_id: int, priority: int) -> CanonicalEvent:
    return CanonicalEvent(
        "INTERRUPT_NOTIFY",
        reference,
        {"interrupt_id": interrupt_id, "priority": priority},
    )


class InterruptNotificationInterfaceTest(unittest.TestCase):
    def test_completion_checks_reference_id_and_causal_lifecycle(self) -> None:
        protocol = build_interrupt_notification_interface()
        session = protocol.open_session()
        initial = session.initial_state()
        notified = session.step(initial, _notify(3, 17, 4))

        self.assertIsNone(notified.fault)
        self.assertFalse(session.is_quiescent(notified.state))

        wrong_id = session.step(
            notified.state,
            CanonicalEvent(
                "INTERRUPT_COMPLETE", 3, {"interrupt_id": 18}
            ),
        )
        self.assertEqual(
            "interrupt_notification.lifecycle.completion_interrupt_id",
            wrong_id.fault.rule,
        )
        self.assertIs(wrong_id.state, notified.state)

        completed = session.step(
            notified.state,
            CanonicalEvent(
                "INTERRUPT_COMPLETE", 3, {"interrupt_id": 17}
            ),
        )
        self.assertIsNone(completed.fault)
        self.assertEqual(((0, 1),), completed.state.causal_edges)
        self.assertTrue(session.is_quiescent(completed.state))


class InterruptControllerTest(unittest.TestCase):
    @staticmethod
    def _system(
        *,
        controller_capacity: int = 4,
        exhaustion_policy: ResourceExhaustionPolicy | str = (
            ResourceExhaustionPolicy.BLOCK
        ),
    ):
        protocol = build_interrupt_notification_interface(
            InterruptNotificationConfig(maximum_outstanding=4)
        )
        sensor_a = VirtualDut(
            "sensor_a",
            {"irq": InterfacePort("irq", protocol, "notifier")},
            backend=CaptureBackend(),
        )
        sensor_b = VirtualDut(
            "sensor_b",
            {"irq": InterfacePort("irq", protocol, "notifier")},
            backend=CaptureBackend(),
        )
        controller = build_edge_interrupt_controller_vdut(
            "controller",
            protocol,
            ingress_ports=("from_sensor_a", "from_sensor_b"),
            target_port="to_cpu",
            capacity=controller_capacity,
            exhaustion_policy=exhaustion_policy,
        )
        target = build_edge_interrupt_target_vdut(
            "cpu", protocol, port_name="irq"
        )
        links = {
            "sensor_a_irq": InterfaceConnection(
                "sensor_a_irq",
                protocol,
                {
                    "notifier": VirtualDutPortRef("sensor_a", "irq"),
                    "handler": VirtualDutPortRef(
                        "controller", "from_sensor_a"
                    ),
                },
            ),
            "sensor_b_irq": InterfaceConnection(
                "sensor_b_irq",
                protocol,
                {
                    "notifier": VirtualDutPortRef("sensor_b", "irq"),
                    "handler": VirtualDutPortRef(
                        "controller", "from_sensor_b"
                    ),
                },
            ),
            "cpu_irq": InterfaceConnection(
                "cpu_irq",
                protocol,
                {
                    "notifier": VirtualDutPortRef("controller", "to_cpu"),
                    "handler": VirtualDutPortRef("cpu", "irq"),
                },
            ),
        }
        return SystemProtocol(
            "edge_interrupt_tree",
            {
                item.name: item
                for item in (sensor_a, sensor_b, controller, target)
            },
            links,
        )

    def test_priority_delivery_waits_for_eoi_then_selects_next(self) -> None:
        system = self._system()
        session = system.open_session()
        state = session.initial_state()

        low_priority = session.step(
            state,
            SystemAction(
                VirtualDutPortRef("sensor_a", "irq"),
                _notify(9, 40, 7),
            ),
        )
        self.assertIsNone(low_priority.fault)
        self.assertEqual(
            ("INTERRUPT_NOTIFY", "INTERRUPT_COMPLETE"),
            tuple(item.event.kind for item in low_priority.emissions),
        )

        high_priority = session.step(
            low_priority.state,
            SystemAction(
                VirtualDutPortRef("sensor_b", "irq"),
                _notify(2, 11, 1),
            ),
        )
        self.assertIsNone(high_priority.fault)
        controller_state = high_priority.state.dut_states["controller"]
        self.assertIsInstance(controller_state, InterruptControllerState)
        self.assertEqual(2, len(controller_state.pending))
        self.assertIsNone(controller_state.active)

        first_delivery = session.step(
            high_priority.state, DutAdvanceAction("controller")
        )
        self.assertIsNone(first_delivery.fault)
        self.assertEqual(
            ("INTERRUPT_NOTIFY",),
            tuple(item.event.kind for item in first_delivery.emissions),
        )
        self.assertEqual(
            11, first_delivery.emissions[0].event.payload["interrupt_id"]
        )

        first_eoi = session.step(
            first_delivery.state, DutAdvanceAction("cpu")
        )
        self.assertIsNone(first_eoi.fault)
        self.assertEqual(
            ("INTERRUPT_COMPLETE", "INTERRUPT_NOTIFY"),
            tuple(item.event.kind for item in first_eoi.emissions),
        )
        self.assertEqual(
            40, first_eoi.emissions[1].event.payload["interrupt_id"]
        )

        second_eoi = session.step(first_eoi.state, DutAdvanceAction("cpu"))
        self.assertIsNone(second_eoi.fault)
        self.assertEqual(
            ("INTERRUPT_COMPLETE",),
            tuple(item.event.kind for item in second_eoi.emissions),
        )
        target_state = second_eoi.state.dut_states["cpu"]
        self.assertIsInstance(target_state, InterruptTargetState)
        self.assertEqual(
            (11, 40),
            tuple(item.interrupt_id for item in target_state.handled),
        )
        final_controller = second_eoi.state.dut_states["controller"]
        self.assertEqual(2, final_controller.completed_count)
        self.assertTrue(session.is_quiescent(second_eoi.state))

        for sensor_name in ("sensor_a", "sensor_b"):
            sensor_state = second_eoi.state.dut_states[sensor_name]
            self.assertIsInstance(sensor_state, CaptureState)
            self.assertEqual(1, len(sensor_state.received))

    def test_controller_capacity_blocks_without_committing_state(self) -> None:
        system = self._system(controller_capacity=1)
        controller = system.virtual_duts["controller"]
        backend = controller.backend
        self.assertIsInstance(backend, PriorityInterruptControllerBackend)
        assert isinstance(backend, PriorityInterruptControllerBackend)
        state = backend.initial_state()

        accepted = backend.accept(
            state, PortInput("from_sensor_a", _notify(0, 1, 1))
        )
        rejected = backend.accept(
            accepted.state,
            PortInput("from_sensor_b", _notify(0, 2, 1)),
        )

        self.assertIsNone(accepted.fault)
        self.assertIsNone(rejected.fault)
        self.assertEqual("notification_entries", rejected.blocked.resource)
        self.assertEqual("from_sensor_b", rejected.blocked.location)
        self.assertEqual(0, rejected.blocked.available)
        self.assertEqual(1, rejected.blocked.capacity)
        self.assertIs(rejected.state, accepted.state)
        self.assertEqual(1, backend.occupancy(rejected.state))

    def test_controller_fault_policy_and_unsupported_error_completion(self) -> None:
        system = self._system(
            controller_capacity=1,
            exhaustion_policy=ResourceExhaustionPolicy.FAULT,
        )
        backend = system.virtual_duts["controller"].backend
        assert isinstance(backend, PriorityInterruptControllerBackend)
        state = backend.initial_state()
        accepted = backend.accept(
            state, PortInput("from_sensor_a", _notify(0, 1, 1))
        )
        rejected = backend.accept(
            accepted.state,
            PortInput("from_sensor_b", _notify(0, 2, 1)),
        )

        self.assertEqual("interrupt_controller.capacity", rejected.fault.rule)
        self.assertIsNone(rejected.blocked)
        self.assertIs(rejected.state, accepted.state)

        with self.assertRaisesRegex(
            ValueError, "no protocol-visible error completion"
        ):
            self._system(
                controller_capacity=1,
                exhaustion_policy=ResourceExhaustionPolicy.ERROR_COMPLETION,
            )

    def test_interrupt_target_blocks_a_second_delivery_until_eoi(self) -> None:
        system = self._system()
        target = system.virtual_duts["cpu"].backend
        state = target.initial_state()
        accepted = target.accept(
            state, PortInput("irq", _notify(0, 3, 2))
        )
        blocked = target.accept(
            accepted.state, PortInput("irq", _notify(1, 4, 1))
        )

        self.assertIsNone(accepted.fault)
        self.assertIsNone(blocked.fault)
        self.assertEqual("active_interrupt_slot", blocked.blocked.resource)
        self.assertEqual("irq", blocked.blocked.location)
        self.assertEqual(0, blocked.blocked.available)
        self.assertEqual(1, blocked.blocked.capacity)
        self.assertIs(blocked.state, accepted.state)


if __name__ == "__main__":
    unittest.main()
