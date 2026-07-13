"""The two VirtualDuts used by the AXI4 read-interleaving experiment."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from protocol_model.core import (
    CanonicalEvent,
    PortDirection,
    PortSpec,
    SemanticFault,
    SemanticStep,
)
from protocol_model.protocols.spec import ProtocolSpec
from protocol_model.virtual_dut import (
    ScriptedSource,
    VirtualDut,
    VirtualDutContract,
    VirtualDutKind,
)


def build_read_initiator(
    spec: ProtocolSpec, *, beats_per_request: int = 2
) -> ScriptedSource[CanonicalEvent]:
    """Virtual input DUT: issue two equal-length reads with distinct IDs."""

    if not 1 <= beats_per_request <= 256:
        raise ValueError("beats_per_request must be in the AXI4 range [1, 256]")

    rng = Random(73)
    ids = tuple(spec.parameters["active_read_ids"])
    events = tuple(
        spec.channel("AR").transfer.sample_constrained(
            rng,
            key=key,
            payload={
                "addr": 0x1000 + key * 0x100,
                "len": beats_per_request - 1,
                "size": 2,
                "burst": "INCR",
            },
        )
        for key in ids[:2]
    )
    return ScriptedSource(events, name="read_interleave_initiator")


@dataclass(frozen=True)
class ResponderState:
    pending: tuple[CanonicalEvent, ...] = ()
    requests: int = 0
    responses: int = 0


class InterleavingReadResponder(
    VirtualDut[CanonicalEvent, ResponderState, CanonicalEvent]
):
    """Virtual output DUT: respond to the later AR first, then alternate IDs."""

    kind = VirtualDutKind.RESPONDER

    def __init__(self, spec: ProtocolSpec):
        self.name = "interleaving_read_responder"
        self.spec = spec
        self.ports = (
            PortSpec("AR", PortDirection.INPUT),
            PortSpec("R", PortDirection.OUTPUT),
        )
        self.capabilities = frozenset({"read_response", "cross_id_interleave"})
        self.contract = VirtualDutContract(
            assumptions=("exactly two distinct-ID AR requests are supplied",),
            guarantees=(
                "the later AR responds and completes first across IDs",
                "each individual burst preserves its own beat order",
            ),
        )
        self.rng = Random(79)

    def initial_state(self) -> ResponderState:
        return ResponderState()

    def is_quiescent(self, state: ResponderState) -> bool:
        return not state.pending

    def step(
        self, state: ResponderState, event: CanonicalEvent
    ) -> SemanticStep[ResponderState, CanonicalEvent]:
        if event.kind != "AR_TRANSFER":
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.input_kind",
                    "responder accepts only AR transfers",
                    "DUT",
                ),
            )
        pending = state.pending + (event,)
        if len(pending) < 2:
            return SemanticStep(
                ResponderState(pending, state.requests + 1, state.responses)
            )
        if len(pending) > 2 or pending[0].key == pending[1].key:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.request_set",
                    "responder requires exactly two distinct IDs",
                    "DUT",
                ),
            )

        outputs = []
        totals = tuple(int(item.payload["len"]) + 1 for item in pending)
        response_order = tuple(reversed(tuple(zip(pending, totals))))
        for beat in range(max(totals)):
            for request, total in response_order:
                if beat >= total:
                    continue
                outputs.append(
                    self.spec.channel("R").transfer.sample_constrained(
                        self.rng,
                        key=request.key,
                        payload={
                            "data": (int(request.key) << 8) | beat,
                            "resp": "OKAY",
                            "last": beat == total - 1,
                        },
                    )
                )
        return SemanticStep(
            ResponderState((), state.requests + 1, state.responses + len(outputs)),
            tuple(outputs),
        )
