"""Small registered VirtualDut building blocks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Sequence, TypeVar

from protocol_model.core import (
    PortDirection,
    PortSpec,
    SemanticFault,
    SemanticStep,
)

from .base import VirtualDut, VirtualDutContract, VirtualDutKind


InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class SinkState(Generic[InputT]):
    received: int = 0
    retained: tuple[InputT, ...] = ()


class Sink(VirtualDut[InputT, SinkState[InputT], object], Generic[InputT]):
    kind = VirtualDutKind.SINK

    def __init__(
        self,
        name: str = "sink",
        *,
        capture: bool = False,
        accepts: Callable[[InputT], bool] = lambda _: True,
    ):
        self.name = name
        self.capture = capture
        self.accepts = accepts
        self.ports = (PortSpec("input", PortDirection.INPUT),)
        self.capabilities = frozenset({"consume", "capture"} if capture else {"consume"})
        self.contract = VirtualDutContract(
            guarantees=("accepted inputs produce no output action",)
        )

    def initial_state(self) -> SinkState[InputT]:
        return SinkState()

    def step(
        self, state: SinkState[InputT], action: InputT
    ) -> SemanticStep[SinkState[InputT], object]:
        if not self.accepts(action):
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.rejected_input",
                    "sink input predicate rejected the action",
                    "DUT",
                ),
            )
        retained = state.retained + (action,) if self.capture else state.retained
        return SemanticStep(SinkState(state.received + 1, retained))


@dataclass(frozen=True)
class EmitNext:
    """Scheduler command that lets a source emit its next scripted action."""


@dataclass(frozen=True)
class ScriptedSourceState(Generic[OutputT]):
    remaining: tuple[OutputT, ...]
    emitted: int = 0


class ScriptedSource(
    VirtualDut[EmitNext, ScriptedSourceState[OutputT], OutputT],
    Generic[OutputT],
):
    kind = VirtualDutKind.SOURCE

    def __init__(self, sequence: Sequence[OutputT], name: str = "scripted_source"):
        self.name = name
        self.sequence = tuple(sequence)
        self.ports = (PortSpec("output", PortDirection.OUTPUT),)
        self.capabilities = frozenset({"scripted_sequence"})
        self.contract = VirtualDutContract(
            guarantees=("outputs preserve the configured sequence order",)
        )

    def initial_state(self) -> ScriptedSourceState[OutputT]:
        return ScriptedSourceState(self.sequence)

    def offers(self, state: ScriptedSourceState[OutputT]):
        return (EmitNext(),) if state.remaining else ()

    def is_quiescent(self, state: ScriptedSourceState[OutputT]) -> bool:
        return not state.remaining

    def step(
        self, state: ScriptedSourceState[OutputT], action: EmitNext
    ) -> SemanticStep[ScriptedSourceState[OutputT], OutputT]:
        if not isinstance(action, EmitNext) or not state.remaining:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.not_enabled",
                    "source has no enabled scripted output",
                    "DUT",
                ),
            )
        return SemanticStep(
            ScriptedSourceState(state.remaining[1:], state.emitted + 1),
            (state.remaining[0],),
        )


@dataclass(frozen=True)
class FunctionResponderState:
    requests: int = 0
    responses: int = 0


class FunctionResponder(
    VirtualDut[InputT, FunctionResponderState, OutputT],
    Generic[InputT, OutputT],
):
    """Turn one input into zero or more outputs through a supplied function."""

    kind = VirtualDutKind.RESPONDER

    def __init__(
        self,
        function: Callable[[InputT], Sequence[OutputT]],
        name: str = "function_responder",
        *,
        capabilities: frozenset[str] = frozenset({"request_response"}),
        contract: VirtualDutContract = VirtualDutContract(),
    ):
        self.name = name
        self.function = function
        self.capabilities = capabilities
        self.contract = contract
        self.ports = (
            PortSpec("request", PortDirection.INPUT),
            PortSpec("response", PortDirection.OUTPUT),
        )

    def initial_state(self) -> FunctionResponderState:
        return FunctionResponderState()

    def step(
        self, state: FunctionResponderState, action: InputT
    ) -> SemanticStep[FunctionResponderState, OutputT]:
        try:
            outputs = tuple(self.function(action))
        except Exception as error:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.backend",
                    f"functional backend failed: {error}",
                    "DUT",
                ),
            )
        return SemanticStep(
            FunctionResponderState(
                state.requests + 1, state.responses + len(outputs)
            ),
            outputs,
        )
