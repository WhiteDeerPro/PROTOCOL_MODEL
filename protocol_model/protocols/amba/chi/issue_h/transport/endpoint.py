"""Finite endpoint mechanisms for the minimal CHI REQ transport path."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticFault,
    SemanticStep,
)

from ..representation import (
    CHI_ISSUE_H_CHANNEL_DOMAIN,
    ChiChannelKind,
    ChiProtocolFlit,
)
from .link import (
    ChiLinkEndpointRef,
    ChiReqTransfer,
    ChiReqTransferKind,
)


@dataclass(frozen=True)
class ChiReqQueuedFlit:
    """One packet-bearing protocol flit waiting at a Transmitter."""

    serial: int
    flit: ChiProtocolFlit
    resource_plane: int


@dataclass(frozen=True)
class ChiReqTxQueueState:
    pending: tuple[ChiReqQueuedFlit, ...] = ()
    next_serial: int = 0
    sent_count: int = 0

    @property
    def depth(self) -> int:
        return len(self.pending)


class ChiReqTxQueue:
    """Bounded, FIFO REQ source independent of Link Credit capacity."""

    def __init__(
        self,
        endpoint: ChiLinkEndpointRef,
        *,
        capacity: int,
        resource_planes: int,
    ) -> None:
        if not isinstance(endpoint, ChiLinkEndpointRef):
            raise TypeError("REQ TX queue requires a CHI endpoint reference")
        if (
            not isinstance(capacity, int)
            or isinstance(capacity, bool)
            or capacity <= 0
        ):
            raise ValueError("REQ TX queue capacity must be positive")
        if (
            not isinstance(resource_planes, int)
            or isinstance(resource_planes, bool)
            or resource_planes <= 0
        ):
            raise ValueError("REQ TX queue requires at least one Resource Plane")
        self.endpoint = endpoint
        self.capacity = capacity
        self.resource_planes = resource_planes

    def initial_state(self) -> ChiReqTxQueueState:
        return ChiReqTxQueueState()

    def enqueue(
        self,
        state: ChiReqTxQueueState,
        flit: ChiProtocolFlit,
        resource_plane: int,
    ) -> SemanticStep[ChiReqTxQueueState, ChiReqQueuedFlit]:
        self._require_state(state)
        if not isinstance(flit, ChiProtocolFlit):
            raise TypeError(
                "REQ TX queue accepts packet-bearing ChiProtocolFlit values"
            )
        classification = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(flit)
        if (
            classification.channel is not ChiChannelKind.REQ
            or not classification.is_protocol_flit
        ):
            raise TypeError("REQ TX queue accepts REQ protocol flits")
        if (
            not isinstance(resource_plane, int)
            or isinstance(resource_plane, bool)
            or not 0 <= resource_plane < self.resource_planes
        ):
            return self._fault(
                state,
                "resource_plane",
                f"REQ Resource Plane {resource_plane!r} is out of range",
            )
        if state.depth >= self.capacity:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    "chi.req_tx_queue.slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.capacity,
                    reason="REQ transmitter queue is full",
                    location=self.endpoint.qualified_name,
                ),
            )
        entry = ChiReqQueuedFlit(state.next_serial, flit, resource_plane)
        candidate = ChiReqTxQueueState(
            state.pending + (entry,),
            state.next_serial + 1,
            state.sent_count,
        )
        return SemanticStep(candidate, (entry,))

    def head(self, state: ChiReqTxQueueState) -> ChiReqQueuedFlit | None:
        self._require_state(state)
        return None if not state.pending else state.pending[0]

    def commit_transfer(
        self,
        state: ChiReqTxQueueState,
        transfer: ChiReqTransfer,
    ) -> SemanticStep[ChiReqTxQueueState, ChiReqQueuedFlit]:
        self._require_state(state)
        if not isinstance(transfer, ChiReqTransfer):
            raise TypeError("REQ TX queue commit requires ChiReqTransfer")
        if transfer.kind is not ChiReqTransferKind.PROTOCOL:
            return self._fault(
                state,
                "transfer_kind",
                "a protocol queue cannot commit a link-maintenance flit",
            )
        head = self.head(state)
        if head is None:
            return self._fault(
                state,
                "empty_commit",
                "the link accepted a protocol flit from an empty TX queue",
            )
        if (
            transfer.flit != head.flit
            or transfer.resource_plane != head.resource_plane
        ):
            return self._fault(
                state,
                "head_mismatch",
                "accepted transfer does not match the REQ FIFO head",
            )
        candidate = ChiReqTxQueueState(
            state.pending[1:],
            state.next_serial,
            state.sent_count + 1,
        )
        return SemanticStep(candidate, (head,))

    def _require_state(self, state: ChiReqTxQueueState) -> None:
        if not isinstance(state, ChiReqTxQueueState):
            raise TypeError("REQ TX queue requires ChiReqTxQueueState")

    def _fault(
        self, state: ChiReqTxQueueState, suffix: str, reason: str
    ) -> SemanticStep[ChiReqTxQueueState, ChiReqQueuedFlit]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"chi.req_tx_queue.{suffix}",
                reason,
                ConstraintScope.VIRTUAL_DUT,
                self.endpoint.qualified_name,
            ),
        )


@dataclass(frozen=True)
class ChiReqCaptureState:
    """Accepted protocol flits plus receiver slots reserved by credits."""

    captured: tuple[ChiReqTransfer, ...]
    reserved_by_plane: tuple[int, ...]
    received_count: int = 0
    returned_credit_count: int = 0

    @property
    def depth(self) -> int:
        return len(self.captured)

    def depth_by_plane(self, plane: int) -> int:
        return sum(
            transfer.resource_plane == plane for transfer in self.captured
        )


class ChiReqCaptureEndpoint:
    """Finite REQ receiver whose free slots govern dedicated L-Credits."""

    def __init__(
        self,
        endpoint: ChiLinkEndpointRef,
        *,
        capacities_by_plane: tuple[int, ...],
        credit_limits_by_plane: tuple[int, ...],
    ) -> None:
        if not isinstance(endpoint, ChiLinkEndpointRef):
            raise TypeError("REQ capture requires a CHI endpoint reference")
        capacities = tuple(capacities_by_plane)
        limits = tuple(credit_limits_by_plane)
        if not capacities or len(capacities) != len(limits):
            raise ValueError(
                "capture and credit capacities require the same planes"
            )
        if any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or item <= 0
            for item in (*capacities, *limits)
        ):
            raise ValueError("capture and credit capacities must be positive")
        if any(limit > capacity for limit, capacity in zip(limits, capacities)):
            raise ValueError("credit limit cannot exceed receiver capacity")
        self.endpoint = endpoint
        self.capacities_by_plane = capacities
        self.credit_limits_by_plane = limits

    def initial_state(self) -> ChiReqCaptureState:
        return ChiReqCaptureState(
            (), tuple(0 for _ in self.capacities_by_plane)
        )

    def grant_vector(
        self,
        state: ChiReqCaptureState,
        *,
        receiving_plane: int | None = None,
    ) -> tuple[bool, ...]:
        self._require_state(state)
        if receiving_plane is not None and not (
            0 <= receiving_plane < len(self.capacities_by_plane)
        ):
            raise ValueError("receiving Resource Plane is out of range")
        return tuple(
            state.reserved_by_plane[plane]
            - int(receiving_plane == plane)
            < credit_limit
            and state.depth_by_plane(plane)
            + int(receiving_plane == plane)
            + state.reserved_by_plane[plane]
            - int(receiving_plane == plane)
            < capacity
            for plane, (capacity, credit_limit) in enumerate(
                zip(
                    self.capacities_by_plane,
                    self.credit_limits_by_plane,
                )
            )
        )

    def apply_frame(
        self,
        state: ChiReqCaptureState,
        grants: tuple[bool, ...],
        transfers: tuple[ChiReqTransfer, ...],
    ) -> SemanticStep[ChiReqCaptureState, ChiReqTransfer]:
        self._require_state(state)
        grants = tuple(grants)
        if len(grants) != len(self.capacities_by_plane):
            return self._fault(
                state,
                "grant_shape",
                "credit grant shape does not match receiver planes",
            )
        if any(type(item) is not bool for item in grants):
            raise TypeError("receiver credit grant entries must be bool")
        reserved = list(state.reserved_by_plane)
        captured = list(state.captured)
        protocol_count = 0
        returned_count = 0

        for transfer in transfers:
            if not isinstance(transfer, ChiReqTransfer):
                raise TypeError("REQ capture accepts ChiReqTransfer values")
            plane = transfer.resource_plane
            if not 0 <= plane < len(reserved):
                return self._fault(
                    state,
                    "transfer_plane",
                    f"accepted transfer uses unknown plane {plane}",
                )
            if reserved[plane] == 0:
                return self._fault(
                    state,
                    "unreserved_transfer",
                    "receiver observed a transfer without an old reservation",
                )
            reserved[plane] -= 1
            if transfer.kind is ChiReqTransferKind.PROTOCOL:
                captured.append(transfer)
                protocol_count += 1
            else:
                returned_count += 1

        for plane, granted in enumerate(grants):
            if granted:
                reserved[plane] += 1

        candidate = ChiReqCaptureState(
            tuple(captured),
            tuple(reserved),
            state.received_count + protocol_count,
            state.returned_credit_count + returned_count,
        )
        for plane, capacity in enumerate(self.capacities_by_plane):
            occupied = candidate.depth_by_plane(plane)
            if occupied + candidate.reserved_by_plane[plane] > capacity:
                return self._fault(
                    state,
                    "capacity",
                    f"REQ RP{plane} receiver slots are overcommitted",
                )
            if (
                candidate.reserved_by_plane[plane]
                > self.credit_limits_by_plane[plane]
            ):
                return self._fault(
                    state,
                    "credit_limit",
                    f"REQ RP{plane} credit reservations exceed their limit",
                )
        return SemanticStep(candidate, tuple(transfers))

    def drain(
        self, state: ChiReqCaptureState, count: int
    ) -> SemanticStep[ChiReqCaptureState, ChiReqTransfer]:
        self._require_state(state)
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise ValueError("REQ capture drain count must be positive")
        if count > state.depth:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    "chi.req_capture.flit",
                    ConstraintScope.VIRTUAL_DUT,
                    required=count,
                    available=state.depth,
                    capacity=sum(self.capacities_by_plane),
                    reason="REQ receiver has fewer captured flits than requested",
                    location=self.endpoint.qualified_name,
                ),
            )
        drained = state.captured[:count]
        candidate = ChiReqCaptureState(
            state.captured[count:],
            state.reserved_by_plane,
            state.received_count,
            state.returned_credit_count,
        )
        return SemanticStep(candidate, drained)

    def _require_state(self, state: ChiReqCaptureState) -> None:
        if not isinstance(state, ChiReqCaptureState):
            raise TypeError("REQ capture requires ChiReqCaptureState")
        if len(state.reserved_by_plane) != len(self.capacities_by_plane):
            raise ValueError("REQ capture state plane count is inconsistent")

    def _fault(
        self, state: ChiReqCaptureState, suffix: str, reason: str
    ) -> SemanticStep[ChiReqCaptureState, ChiReqTransfer]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"chi.req_capture.{suffix}",
                reason,
                ConstraintScope.VIRTUAL_DUT,
                self.endpoint.qualified_name,
            ),
        )


__all__ = [
    "ChiReqCaptureEndpoint",
    "ChiReqCaptureState",
    "ChiReqQueuedFlit",
    "ChiReqTxQueue",
    "ChiReqTxQueueState",
]
