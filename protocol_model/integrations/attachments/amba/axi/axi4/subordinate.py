"""Burst-aware AXI4 subordinate attachment for a local AddressSpace."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import LinkProtocol
from protocol_model.link.amba.axi.axi4 import transfer_count
from protocol_model.link.amba.axi.axi4.burst import write_strobe_violation
from protocol_model.semantics import CanonicalEvent, ConstraintScope, SemanticFault
from protocol_model.virtual_dut.address.access import (
    AccessResult,
    AddressAccess,
    AddressRead,
    AddressWrite,
    ByteOrder,
)
from protocol_model.virtual_dut.attachments.address import AttachmentEmission
from protocol_model.virtual_dut.attachments.base import ProtocolAttachment
from protocol_model.virtual_dut.attachments.validation import (
    incoming_event_fault,
    outgoing_event_fault,
)

from .common import (
    address_attributes,
    aggregate_write_response,
    beat_access_geometry,
    event_is_forbidden,
    extract_beat_strobes,
    extract_beat_value,
    place_beat_value,
    require_axi4_address_protocol,
    result_response,
)


@dataclass(frozen=True)
class Axi4BurstRequest:
    """One accepted AXI request represented as ordered local byte accesses."""

    kind: str
    descriptor: CanonicalEvent
    accesses: tuple[AddressAccess, ...]

    def __post_init__(self) -> None:
        expected = "AR" if self.kind == "READ" else "AW"
        if self.kind not in {"READ", "WRITE"}:
            raise ValueError("AXI4 burst request kind must be READ or WRITE")
        if self.descriptor.kind != expected:
            raise ValueError(
                f"AXI4 {self.kind} burst requires an {expected} descriptor"
            )
        if not self.accesses:
            raise ValueError("AXI4 burst request requires at least one access")


@dataclass(frozen=True)
class Axi4BurstDecode:
    state: object
    request: Axi4BurstRequest | None = None
    fault: SemanticFault | None = None


@dataclass(frozen=True)
class Axi4SubordinateState:
    """AW/W transport state; completed pairs are drained immediately."""

    pending_addresses: tuple[CanonicalEvent, ...] = ()
    completed_data: tuple[tuple[CanonicalEvent, ...], ...] = ()
    current_data: tuple[CanonicalEvent, ...] = ()


class Axi4AddressSpaceAttachment(ProtocolAttachment):
    """Decode normal AXI4 bursts for synchronous AddressSpace execution.

    The attachment owns only the single-port transport relation: W burst
    assembly, ID-less AW/W FIFO join, byte-lane conversion, and response
    encoding. Address state and per-beat execution remain in the backend.
    """

    role = "subordinate"

    def __init__(
        self,
        protocol: LinkProtocol,
        *,
        byte_order: ByteOrder | str = ByteOrder.LITTLE,
    ) -> None:
        self.byte_order = require_axi4_address_protocol(
            protocol, self.role, byte_order
        )
        self.protocol = protocol
        self.data_width = int(protocol.parameters["data_width"])
        self.bus_bytes = self.data_width // 8

    def initial_state(self) -> Axi4SubordinateState:
        return Axi4SubordinateState()

    def decode_request(
        self, state: object, event: CanonicalEvent
    ) -> Axi4BurstDecode:
        if not isinstance(state, Axi4SubordinateState):
            raise TypeError(
                "Axi4AddressSpaceAttachment requires Axi4SubordinateState"
            )
        fault = incoming_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="axi4_address_space_attachment",
        )
        if fault is not None:
            return Axi4BurstDecode(state, fault=fault)
        if event_is_forbidden(self.protocol, event.kind):
            return Axi4BurstDecode(
                state,
                fault=self._fault(
                    "profile",
                    f"AXI4 link profile disables {event.kind}",
                ),
            )

        if event.kind == "AR":
            descriptor_fault = self._descriptor_fault(event)
            if descriptor_fault is not None:
                return Axi4BurstDecode(state, fault=descriptor_fault)
            return Axi4BurstDecode(state, self._read_request(event))

        if event.kind == "AW":
            descriptor_fault = self._descriptor_fault(event)
            if descriptor_fault is not None:
                return Axi4BurstDecode(state, fault=descriptor_fault)
            candidate = Axi4SubordinateState(
                state.pending_addresses + (event,),
                state.completed_data,
                state.current_data,
            )
            prefix_fault = self._current_prefix_fault(candidate)
            if prefix_fault is not None:
                return Axi4BurstDecode(state, fault=prefix_fault)
            return self._drain_join(state, candidate)

        if event.kind != "W":
            return Axi4BurstDecode(
                state,
                fault=self._fault(
                    "direction",
                    f"AXI4 subordinate cannot consume {event.kind!r}",
                ),
            )

        current = state.current_data + (event,)
        if state.pending_addresses:
            prefix_fault = self._data_prefix_fault(
                state.pending_addresses[0], current
            )
            if prefix_fault is not None:
                return Axi4BurstDecode(state, fault=prefix_fault)
        if bool(event.payload["last"]):
            candidate = Axi4SubordinateState(
                state.pending_addresses,
                state.completed_data + (current,),
                (),
            )
        else:
            candidate = Axi4SubordinateState(
                state.pending_addresses,
                state.completed_data,
                current,
            )
        return self._drain_join(state, candidate)

    def encode_completion(
        self,
        state: object,
        request: Axi4BurstRequest,
        results: tuple[AccessResult, ...],
    ) -> AttachmentEmission:
        if not isinstance(state, Axi4SubordinateState):
            raise TypeError(
                "Axi4AddressSpaceAttachment requires Axi4SubordinateState"
            )
        if not isinstance(request, Axi4BurstRequest):
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "context", "AXI4 AddressSpace backend lost its burst context"
                ),
            )
        results = tuple(results)
        if len(results) != len(request.accesses):
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "result_count",
                    "AXI4 burst completion count does not match its beat count",
                ),
            )

        if request.kind == "WRITE":
            events = (
                CanonicalEvent(
                    "B",
                    request.descriptor.key,
                    {"resp": aggregate_write_response(results)},
                ),
            )
        else:
            events_list: list[CanonicalEvent] = []
            final_index = len(results) - 1
            for index, result in enumerate(results):
                if result.succeeded and result.data is None:
                    return AttachmentEmission(
                        state,
                        fault=self._fault(
                            "read_data",
                            "successful AXI4 read beat requires response data",
                        ),
                    )
                try:
                    data = (
                        place_beat_value(
                            int(result.data),
                            request.descriptor,
                            index,
                            bus_bytes=self.bus_bytes,
                        )
                        if result.succeeded
                        else 0
                    )
                except (TypeError, ValueError) as error:
                    return AttachmentEmission(
                        state, fault=self._fault("read_data", str(error))
                    )
                events_list.append(
                    CanonicalEvent(
                        "R",
                        request.descriptor.key,
                        {
                            "data": data,
                            "resp": result_response(result),
                            "last": index == final_index,
                        },
                    )
                )
            events = tuple(events_list)

        for event in events:
            fault = outgoing_event_fault(
                self.protocol,
                self.role,
                event,
                rule_prefix="axi4_address_space_attachment",
            )
            if fault is not None:
                return AttachmentEmission(state, fault=fault)
            if event_is_forbidden(self.protocol, event.kind):
                return AttachmentEmission(
                    state,
                    fault=self._fault(
                        "profile",
                        f"AXI4 link profile disables {event.kind}",
                    ),
                )
        return AttachmentEmission(state, events)

    def is_quiescent(self, state: object) -> bool:
        return (
            isinstance(state, Axi4SubordinateState)
            and not state.pending_addresses
            and not state.completed_data
            and not state.current_data
        )

    def _read_request(self, descriptor: CanonicalEvent) -> Axi4BurstRequest:
        attributes = address_attributes(descriptor)
        accesses = []
        for index in range(transfer_count(descriptor)):
            address, size, _ = beat_access_geometry(
                descriptor, index, bus_bytes=self.bus_bytes
            )
            accesses.append(AddressRead(address, size, attributes))
        return Axi4BurstRequest("READ", descriptor, tuple(accesses))

    def _write_request(
        self,
        descriptor: CanonicalEvent,
        data: tuple[CanonicalEvent, ...],
    ) -> Axi4BurstRequest:
        reason = self._complete_data_violation(descriptor, data)
        if reason is not None:
            raise ValueError(reason)
        attributes = address_attributes(descriptor)
        accesses = []
        for index, beat in enumerate(data):
            address, size, _ = beat_access_geometry(
                descriptor, index, bus_bytes=self.bus_bytes
            )
            accesses.append(
                AddressWrite(
                    address,
                    size,
                    extract_beat_value(
                        int(beat.payload["data"]),
                        descriptor,
                        index,
                        bus_bytes=self.bus_bytes,
                    ),
                    extract_beat_strobes(
                        int(beat.payload["strb"]),
                        descriptor,
                        index,
                        bus_bytes=self.bus_bytes,
                    ),
                    attributes,
                )
            )
        return Axi4BurstRequest("WRITE", descriptor, tuple(accesses))

    def _drain_join(
        self,
        original: Axi4SubordinateState,
        candidate: Axi4SubordinateState,
    ) -> Axi4BurstDecode:
        if not candidate.pending_addresses or not candidate.completed_data:
            return Axi4BurstDecode(candidate)
        descriptor = candidate.pending_addresses[0]
        data = candidate.completed_data[0]
        try:
            request = self._write_request(descriptor, data)
        except ValueError as error:
            return Axi4BurstDecode(
                original, fault=self._fault("write_join", str(error))
            )
        next_state = Axi4SubordinateState(
            candidate.pending_addresses[1:],
            candidate.completed_data[1:],
            candidate.current_data,
        )
        return Axi4BurstDecode(next_state, request)

    def _current_prefix_fault(
        self, state: Axi4SubordinateState
    ) -> SemanticFault | None:
        if not state.pending_addresses or not state.current_data:
            return None
        return self._data_prefix_fault(
            state.pending_addresses[0], state.current_data
        )

    def _data_prefix_fault(
        self,
        descriptor: CanonicalEvent,
        data: tuple[CanonicalEvent, ...],
    ) -> SemanticFault | None:
        expected = transfer_count(descriptor)
        if len(data) > expected:
            return self._fault(
                "write_beat_count",
                f"W burst exceeded AW length of {expected} beats",
            )
        for index, beat in enumerate(data):
            expected_last = index + 1 == expected
            if bool(beat.payload["last"]) is not expected_last:
                return self._fault(
                    "write_last",
                    f"W beat {index + 1}/{expected} requires last={expected_last}",
                )
            reason = write_strobe_violation(
                descriptor, index, beat, bus_bytes=self.bus_bytes
            )
            if reason is not None:
                return self._fault("write_strobes", reason)
        return None

    def _complete_data_violation(
        self,
        descriptor: CanonicalEvent,
        data: tuple[CanonicalEvent, ...],
    ) -> str | None:
        expected = transfer_count(descriptor)
        if len(data) != expected:
            return (
                f"completed W burst has {len(data)} beats; AW requires {expected}"
            )
        fault = self._data_prefix_fault(descriptor, data)
        return None if fault is None else fault.reason

    def _descriptor_fault(
        self, descriptor: CanonicalEvent
    ) -> SemanticFault | None:
        if int(descriptor.payload["lock"]):
            return self._fault(
                "exclusive",
                "generic AXI4 AddressSpace endpoint has no Exclusive Access Monitor",
            )
        return None

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"axi4_address_space_attachment.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )
