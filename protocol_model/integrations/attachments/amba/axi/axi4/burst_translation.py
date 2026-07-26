"""Full AXI4 ingress codec for typed address-burst translation."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.axi.axi4 import AXI4_FAMILY
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    SemanticFault,
)
from protocol_model.virtual_dut.address.burst import (
    AddressBurst,
    AddressBurstResult,
)
from protocol_model.virtual_dut.attachments.address_operation import (
    AddressOperationCompleterAttachment,
    AddressOperationDecode,
)
from protocol_model.virtual_dut.attachments.base import AttachmentEmission
from protocol_model.virtual_dut.translation.signature import OperationSignature
from protocol_model.virtual_dut.attachments.validation import (
    outgoing_event_fault,
)

from .common import (
    aggregate_write_response,
    event_is_forbidden,
    place_beat_value,
    result_response,
)
from .subordinate import (
    Axi4AddressSpaceAttachment,
    Axi4SubordinateState,
)


def axi4_raw_burst_signature(protocol: InterfaceProtocol) -> OperationSignature:
    """Return the AXI-attribute interpretation of ``AddressBurst`` DTOs."""

    if protocol.interface_family != AXI4_FAMILY:
        raise ValueError("AXI4 burst signature requires an AXI4 InterfaceProtocol")
    return OperationSignature(
        protocol.interface_family,
        "raw_address_burst",
        "1",
        (AddressBurst,),
        (AddressBurstResult,),
    )


@dataclass(frozen=True)
class Axi4BurstAssemblyProfile:
    """Finite storage used before AW/W fragments form a parent operation."""

    max_pending_aw: int = 8
    max_pre_aw_w_bursts: int = 8
    max_buffered_w_beats: int = 256

    def __post_init__(self) -> None:
        for name in (
            "max_pending_aw",
            "max_pre_aw_w_bursts",
            "max_buffered_w_beats",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class Axi4BurstReplyContext:
    """Wire information retained after accesses move into ``AddressBurst``."""

    kind: str
    descriptor: CanonicalEvent
    beat_count: int

    def __post_init__(self) -> None:
        expected = "AR" if self.kind == "READ" else "AW"
        if self.kind not in {"READ", "WRITE"}:
            raise ValueError("AXI4 burst reply kind must be READ or WRITE")
        if self.descriptor.kind != expected:
            raise ValueError(
                f"AXI4 {self.kind} reply context requires {expected}"
            )
        if (
            not isinstance(self.beat_count, int)
            or isinstance(self.beat_count, bool)
            or self.beat_count <= 0
        ):
            raise ValueError("AXI4 burst reply beat count must be positive")


class Axi4BurstTranslationAttachment(AddressOperationCompleterAttachment):
    """Join AXI channels into a canonical burst and encode its R/B result.

    AW/W assembly and AXI byte-lane interpretation remain port-local.  The
    reply context retains the descriptor, direction, ID, and beat count while
    the ordered accesses are owned by the translation executor.
    """

    role = "subordinate"

    def __init__(
        self,
        protocol: InterfaceProtocol,
        *,
        byte_order="little",
        assembly_profile: Axi4BurstAssemblyProfile | None = None,
    ) -> None:
        self._decoder = Axi4AddressSpaceAttachment(
            protocol, byte_order=byte_order
        )
        self.protocol = protocol
        self.byte_order = self._decoder.byte_order
        self.bus_bytes = self._decoder.bus_bytes
        self.assembly_profile = (
            Axi4BurstAssemblyProfile()
            if assembly_profile is None
            else assembly_profile
        )
        if not isinstance(
            self.assembly_profile, Axi4BurstAssemblyProfile
        ):
            raise TypeError(
                "AXI4 burst assembly profile has the wrong type"
            )
        self.operation_signature = axi4_raw_burst_signature(protocol)

    def initial_state(self) -> Axi4SubordinateState:
        return self._decoder.initial_state()

    def decode_operation(
        self, state: object, event: CanonicalEvent
    ) -> AddressOperationDecode:
        decoded = self._decoder.decode_request(state, event)
        if decoded.fault is not None:
            return AddressOperationDecode(state, fault=decoded.fault)
        capacity_fault = self._assembly_capacity_fault(decoded.state)
        if capacity_fault is not None:
            return AddressOperationDecode(state, fault=capacity_fault)
        if decoded.request is None:
            return AddressOperationDecode(decoded.state)
        request = decoded.request
        burst = AddressBurst(request.accesses)
        return AddressOperationDecode(
            decoded.state,
            burst,
            Axi4BurstReplyContext(
                request.kind,
                request.descriptor,
                burst.beat_count,
            ),
        )

    def encode_operation_completion(
        self, state: object, context: object | None, result: object
    ) -> AttachmentEmission:
        if not isinstance(state, Axi4SubordinateState):
            raise TypeError(
                "Axi4BurstTranslationAttachment requires "
                "Axi4SubordinateState"
            )
        if not isinstance(context, Axi4BurstReplyContext):
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "context", "AXI4 burst translation lost its reply context"
                ),
            )
        if not isinstance(result, AddressBurstResult):
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "result_type",
                    "AXI4 burst translation requires AddressBurstResult",
                ),
            )
        if result.beat_count != context.beat_count:
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "result_count",
                    "AXI4 burst result count does not match its descriptor",
                ),
            )

        if context.kind == "WRITE":
            events = (
                CanonicalEvent(
                    "B",
                    context.descriptor.key,
                    {"resp": aggregate_write_response(result.results)},
                ),
            )
        else:
            final_index = result.beat_count - 1
            read_events: list[CanonicalEvent] = []
            for index, beat_result in enumerate(result.results):
                if beat_result.succeeded and beat_result.data is None:
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
                            int(beat_result.data),
                            context.descriptor,
                            index,
                            bus_bytes=self.bus_bytes,
                        )
                        if beat_result.succeeded
                        else 0
                    )
                except (TypeError, ValueError) as error:
                    return AttachmentEmission(
                        state,
                        fault=self._fault("read_data", str(error)),
                    )
                read_events.append(
                    CanonicalEvent(
                        "R",
                        context.descriptor.key,
                        {
                            "data": data,
                            "resp": result_response(beat_result),
                            "last": index == final_index,
                        },
                    )
                )
            events = tuple(read_events)

        for event in events:
            fault = outgoing_event_fault(
                self.protocol,
                self.role,
                event,
                rule_prefix="axi4_burst_translation",
            )
            if fault is not None:
                return AttachmentEmission(state, fault=fault)
            if event_is_forbidden(self.protocol, event.kind):
                return AttachmentEmission(
                    state,
                    fault=self._fault(
                        "profile",
                        f"AXI4 interface profile disables {event.kind}",
                    ),
                )
        return AttachmentEmission(state, events)

    def is_quiescent(self, state: object) -> bool:
        return self._decoder.is_quiescent(state)

    def _assembly_capacity_fault(
        self, state: object
    ) -> SemanticFault | None:
        if not isinstance(state, Axi4SubordinateState):
            return self._fault(
                "assembly_state", "AXI4 decoder returned an unexpected state"
            )
        profile = self.assembly_profile
        if len(state.pending_addresses) > profile.max_pending_aw:
            return self._fault(
                "pending_aw_capacity",
                "pending AXI AW capacity is full "
                f"({profile.max_pending_aw})",
            )
        if len(state.completed_data) > profile.max_pre_aw_w_bursts:
            return self._fault(
                "pre_aw_w_capacity",
                "complete pre-AW W burst capacity is full "
                f"({profile.max_pre_aw_w_bursts})",
            )
        buffered_w_beats = len(state.current_data) + sum(
            len(item) for item in state.completed_data
        )
        if buffered_w_beats > profile.max_buffered_w_beats:
            return self._fault(
                "w_beat_capacity",
                "buffered AXI W beat capacity is full "
                f"({profile.max_buffered_w_beats})",
            )
        return None

    @staticmethod
    def _fault(suffix: str, reason: str) -> SemanticFault:
        return SemanticFault(
            f"axi4_burst_translation.{suffix}",
            reason,
            ConstraintScope.VIRTUAL_DUT,
        )


__all__ = [
    "Axi4BurstAssemblyProfile",
    "Axi4BurstReplyContext",
    "Axi4BurstTranslationAttachment",
    "axi4_raw_burst_signature",
]
