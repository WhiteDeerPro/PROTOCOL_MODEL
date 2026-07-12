"""Stateful, non-terminating virtual AXI read forwarding bridge."""

from __future__ import annotations

from dataclasses import dataclass, replace

from protocol_model.core import (
    CanonicalEvent,
    PortDirection,
    PortSpec,
    SemanticFault,
    SemanticStep,
)
from protocol_model.virtual_dut import (
    VirtualDut,
    VirtualDutContract,
    VirtualDutKind,
)


@dataclass(frozen=True)
class ReadCorrelation:
    upstream_id: int
    downstream_id: int
    remaining: int


@dataclass(frozen=True)
class BridgeState:
    pending: tuple[ReadCorrelation, ...] = ()
    next_downstream_id: int = 0


@dataclass(frozen=True)
class BridgeInput:
    side: str
    event: CanonicalEvent


@dataclass(frozen=True)
class BridgeOutput:
    side: str
    event: CanonicalEvent


class AxiReadBridge(
    VirtualDut[BridgeInput, BridgeState, BridgeOutput]
):
    """Forward AR downstream and correlate R beats back upstream."""

    name = "axi_read_bridge"
    kind = VirtualDutKind.TRANSFORM
    capabilities = frozenset({"axi_read", "id_remap", "correlation"})
    contract = VirtualDutContract(
        assumptions=("upstream AR and downstream R actions are AXI-valid",),
        guarantees=("each downstream R beat is mapped to its upstream ID",),
        invariants=("remaining correlation beats never become negative",),
    )
    ports = (
        PortSpec("upstream_ar", PortDirection.INPUT),
        PortSpec("downstream_ar", PortDirection.OUTPUT),
        PortSpec("downstream_r", PortDirection.INPUT),
        PortSpec("upstream_r", PortDirection.OUTPUT),
    )

    def __init__(self, *, downstream_id_width: int):
        self.id_count = 1 << downstream_id_width

    def initial_state(self) -> BridgeState:
        return BridgeState()

    def is_quiescent(self, state: BridgeState) -> bool:
        return not state.pending

    def step(
        self, state: BridgeState, action: BridgeInput
    ) -> SemanticStep[BridgeState, BridgeOutput]:
        event = action.event
        if action.side == "upstream" and event.kind == "AR_TRANSFER":
            used = {token.downstream_id for token in state.pending}
            downstream_id = next(
                (
                    (state.next_downstream_id + offset) % self.id_count
                    for offset in range(self.id_count)
                    if (state.next_downstream_id + offset) % self.id_count not in used
                ),
                None,
            )
            if downstream_id is None:
                return SemanticStep(
                    state,
                    fault=SemanticFault(
                        f"{self.name}.id_capacity",
                        "no downstream transaction ID is available",
                        "DUT",
                    ),
                )
            token = ReadCorrelation(
                int(event.key), downstream_id, int(event.payload["len"]) + 1
            )
            forwarded = replace(event, key=downstream_id, source=self.name)
            return SemanticStep(
                BridgeState(
                    state.pending + (token,), (downstream_id + 1) % self.id_count
                ),
                (BridgeOutput("downstream", forwarded),),
            )

        if action.side == "downstream" and event.kind == "R_TRANSFER":
            index = next(
                (
                    index
                    for index, token in enumerate(state.pending)
                    if token.downstream_id == event.key
                ),
                None,
            )
            if index is None:
                return SemanticStep(
                    state,
                    fault=SemanticFault(
                        f"{self.name}.orphan_response",
                        f"downstream R ID {event.key!r} has no correlation token",
                        "DUT",
                    ),
                )
            token = state.pending[index]
            expected_last = token.remaining == 1
            if event.payload["last"] is not expected_last:
                return SemanticStep(
                    state,
                    fault=SemanticFault(
                        f"{self.name}.last",
                        f"correlation requires RLAST={expected_last}",
                        "DUT",
                    ),
                )
            pending = list(state.pending)
            if expected_last:
                del pending[index]
            else:
                pending[index] = replace(token, remaining=token.remaining - 1)
            forwarded = replace(event, key=token.upstream_id, source=self.name)
            return SemanticStep(
                BridgeState(tuple(pending), state.next_downstream_id),
                (BridgeOutput("upstream", forwarded),),
            )

        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.alphabet",
                f"unexpected {action.side} action {event.kind}",
                "DUT",
            ),
        )
