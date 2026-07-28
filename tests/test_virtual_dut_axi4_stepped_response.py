from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.endpoints import (
    build_axi4_address_space_vdut,
)
from protocol_model.protocols.amba.axi.axi4 import (
    Axi4Config,
    build_axi4_interface,
)
from protocol_model.semantics import CanonicalEvent
from protocol_model.system import DutAdvanceAction, SystemAction, SystemProtocol
from protocol_model.virtual_dut import (
    AddressSpace,
    CaptureBackend,
    EmissionBatchScheduling,
    InterfacePort,
    MemoryRegion,
    PortInput,
    SteppedEmissionBackend,
    SteppedEmissionProfile,
    VirtualDut,
    constant_emission_wait,
)
from protocol_model.visualization import DutRealizationView, project_virtual_dut


def _read(*, key: int, address: int, length: int) -> CanonicalEvent:
    return CanonicalEvent(
        "AR",
        key,
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


class Axi4SteppedResponseTest(unittest.TestCase):
    def _system(
        self, profile: SteppedEmissionProfile
    ) -> tuple[SystemProtocol, object]:
        protocol = build_axi4_interface(Axi4Config(data_width=32))
        manager = VirtualDut(
            "manager",
            {"axi": InterfacePort("axi", protocol, "manager")},
            backend=CaptureBackend(),
        )
        memory = build_axi4_address_space_vdut(
            "memory",
            protocol,
            AddressSpace(
                (
                    MemoryRegion(
                        "ram",
                        0x100,
                        base_address=0x1000,
                        initial_content=bytes.fromhex(
                            "010000000200000003000000"
                        ),
                    ),
                )
            ),
            response_profile=profile,
        )
        system = SystemProtocol.from_interface(
            "axi4_stepped_response",
            connection_name="axi",
            protocol=protocol,
            endpoints={
                "manager": (manager, "axi"),
                "subordinate": (memory, "axi"),
            },
        )
        return system, system.connections["axi"].endpoints["manager"]

    @staticmethod
    def _response_events(step) -> tuple[CanonicalEvent, ...]:
        return tuple(item.event for item in step.emissions if item.event.kind == "R")

    def test_read_burst_can_insert_empty_advances_between_r_beats(self) -> None:
        system, manager = self._system(
            SteppedEmissionProfile(
                capacity_events=8,
                wait_policy=constant_emission_wait(
                    initial_wait_steps=1,
                    inter_event_wait_steps=1,
                ),
            )
        )
        session = system.open_session()
        issued = session.step(
            session.initial_state(),
            SystemAction(
                manager,
                _read(key=7, address=0x1000, length=2),
            ),
        )

        self.assertIsNone(issued.fault)
        self.assertEqual((), self._response_events(issued))
        self.assertFalse(session.is_quiescent(issued.state))

        states = [issued]
        for _ in range(6):
            states.append(
                session.step(states[-1].state, DutAdvanceAction("memory"))
            )

        self.assertEqual(
            (0, 1, 0, 1, 0, 1),
            tuple(len(self._response_events(item)) for item in states[1:]),
        )
        responses = tuple(
            self._response_events(item)[0]
            for item in (states[2], states[4], states[6])
        )
        self.assertEqual((1, 2, 3), tuple(item.payload["data"] for item in responses))
        self.assertEqual((False, False, True), tuple(item.payload["last"] for item in responses))
        self.assertEqual((7, 7, 7), tuple(item.key for item in responses))
        self.assertTrue(session.is_quiescent(states[-1].state))

    def test_complete_response_batch_reserves_finite_beat_capacity(self) -> None:
        system, manager = self._system(
            SteppedEmissionProfile(capacity_events=3)
        )
        session = system.open_session()
        first = session.step(
            session.initial_state(),
            SystemAction(
                manager,
                _read(key=1, address=0x1000, length=1),
            ),
        )
        blocked = session.step(
            first.state,
            SystemAction(
                manager,
                _read(key=2, address=0x1004, length=1),
            ),
        )

        self.assertIsNone(first.fault)
        self.assertIsNotNone(blocked.blocked)
        assert blocked.blocked is not None
        self.assertEqual(
            "memory.deferred_emission_buffer", blocked.blocked.resource
        )
        self.assertEqual(2, blocked.blocked.required)
        self.assertEqual(1, blocked.blocked.available)
        self.assertIs(blocked.state, first.state)

        released = session.step(first.state, DutAdvanceAction("memory"))
        retried = session.step(
            released.state,
            SystemAction(
                manager,
                _read(key=2, address=0x1004, length=1),
            ),
        )
        self.assertIsNone(retried.blocked)
        self.assertEqual((), self._response_events(retried))

    def test_constructed_projection_shows_response_fifo_and_stepper(self) -> None:
        system, _manager = self._system(
            SteppedEmissionProfile(capacity_events=8)
        )

        projected = project_virtual_dut(system.virtual_duts["memory"])

        self.assertIs(projected.realization, DutRealizationView.CONSTRUCTED)
        self.assertEqual("SteppedEmissionBackend", projected.backend_name)
        component_ids = {item.id for item in projected.components}
        self.assertTrue(
            {"inner_backend", "emission_fifo", "emission_service"}
            <= component_ids
        )

    def test_round_robin_interleaves_read_beats_from_different_ids(self) -> None:
        system, manager = self._system(
            SteppedEmissionProfile(
                capacity_events=8,
                scheduling=EmissionBatchScheduling.ROUND_ROBIN,
            )
        )
        session = system.open_session()
        first = session.step(
            session.initial_state(),
            SystemAction(
                manager,
                _read(key=1, address=0x1000, length=2),
            ),
        )
        second = session.step(
            first.state,
            SystemAction(
                manager,
                _read(key=2, address=0x1004, length=2),
            ),
        )

        responses = []
        current = second
        for _ in range(6):
            current = session.step(
                current.state, DutAdvanceAction("memory")
            )
            responses.extend(self._response_events(current))

        self.assertEqual((1, 2, 1, 2, 1, 2), tuple(item.key for item in responses))
        self.assertEqual(
            (False, False, False, False, True, True),
            tuple(item.payload["last"] for item in responses),
        )
        self.assertEqual(
            (1, 2, 2, 3, 3, 0),
            tuple(item.payload["data"] for item in responses),
        )

    def test_round_robin_does_not_interleave_later_burst_with_same_id(self) -> None:
        system, manager = self._system(
            SteppedEmissionProfile(
                capacity_events=8,
                scheduling="round_robin",
            )
        )
        session = system.open_session()
        first = session.step(
            session.initial_state(),
            SystemAction(
                manager,
                _read(key=3, address=0x1000, length=1),
            ),
        )
        second = session.step(
            first.state,
            SystemAction(
                manager,
                _read(key=3, address=0x1008, length=1),
            ),
        )

        responses = []
        current = second
        for _ in range(4):
            current = session.step(
                current.state, DutAdvanceAction("memory")
            )
            responses.extend(self._response_events(current))

        self.assertEqual((1, 2, 3, 0), tuple(
            item.payload["data"] for item in responses
        ))
        self.assertEqual((False, True, False, True), tuple(
            item.payload["last"] for item in responses
        ))

    def test_round_robin_services_three_live_ids_without_starvation(self) -> None:
        system, manager = self._system(
            SteppedEmissionProfile(
                capacity_events=8,
                scheduling="round_robin",
            )
        )
        session = system.open_session()
        current = session.step(
            session.initial_state(),
            SystemAction(
                manager,
                _read(key=1, address=0x1000, length=1),
            ),
        )
        for key, address in ((2, 0x1004), (3, 0x1008)):
            current = session.step(
                current.state,
                SystemAction(
                    manager,
                    _read(key=key, address=address, length=1),
                ),
            )

        ids = []
        for _ in range(6):
            current = session.step(
                current.state, DutAdvanceAction("memory")
            )
            ids.extend(item.key for item in self._response_events(current))

        self.assertEqual((1, 2, 3, 1, 2, 3), tuple(ids))

    def test_prepared_offer_remains_owned_until_explicit_accept(self) -> None:
        system, _manager = self._system(
            SteppedEmissionProfile(capacity_events=4)
        )
        backend = system.virtual_duts["memory"].backend
        self.assertIsInstance(backend, SteppedEmissionBackend)
        assert isinstance(backend, SteppedEmissionBackend)

        queued = backend.accept(
            backend.initial_state(),
            PortInput(
                "axi",
                _read(key=5, address=0x1000, length=1),
            ),
        )
        prepared = backend.prepare_offer(queued.state)
        first_offer = backend.current_offer(prepared.state)
        held = backend.prepare_offer(prepared.state)
        second_offer = backend.current_offer(held.state)

        self.assertIsNotNone(first_offer)
        self.assertEqual(first_offer, second_offer)
        self.assertIs(prepared.state, held.state)
        self.assertEqual((2, 4), backend.pending_usage(held.state))

        accepted = backend.accept_offer(held.state)
        self.assertEqual(1, len(accepted.emissions))
        self.assertEqual("R", accepted.emissions[0].event.kind)
        self.assertIsNone(backend.current_offer(accepted.state))
        self.assertEqual((1, 4), backend.pending_usage(accepted.state))


if __name__ == "__main__":
    unittest.main()
