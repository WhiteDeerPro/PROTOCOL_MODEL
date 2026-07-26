"""Small port-facing backends used as fixtures and composition leaves."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from protocol_model.semantics import ConstraintScope, SemanticFault

from .base import VirtualDutBackend
from .transition import DutTransition, PortEmission, PortInput


class NoOpBackend(VirtualDutBackend):
    """Consume delivered port inputs without state changes or emissions."""

    def initial_state(self) -> object:
        return None

    def accept(self, state: object, action: PortInput) -> DutTransition:
        return DutTransition(state)


@dataclass(frozen=True)
class CaptureState:
    received: tuple[PortInput, ...] = ()


class CaptureBackend(VirtualDutBackend):
    """Small backend useful for collecting protocol-visible inputs."""

    def __init__(
        self, accepts: Callable[[PortInput], bool] = lambda _action: True
    ) -> None:
        self.accepts = accepts

    def initial_state(self) -> CaptureState:
        return CaptureState()

    def accept(self, state: object, action: PortInput) -> DutTransition:
        assert isinstance(state, CaptureState)
        if not self.accepts(action):
            return DutTransition(
                state,
                fault=SemanticFault(
                    "capture.rejected_input",
                    "VirtualDut input predicate rejected the event",
                    ConstraintScope.VIRTUAL_DUT,
                ),
            )
        return DutTransition(CaptureState(state.received + (action,)))


@dataclass(frozen=True)
class FunctionBackendState:
    received: int = 0
    emitted: int = 0


class FunctionBackend(VirtualDutBackend):
    """A compact backend for pure protocol-visible event transformations."""

    def __init__(
        self, function: Callable[[PortInput], Sequence[PortEmission]]
    ) -> None:
        self.function = function

    def initial_state(self) -> FunctionBackendState:
        return FunctionBackendState()

    def accept(self, state: object, action: PortInput) -> DutTransition:
        assert isinstance(state, FunctionBackendState)
        try:
            emissions = tuple(self.function(action))
        except Exception as error:
            return DutTransition(
                state,
                fault=SemanticFault(
                    "function_backend.failure",
                    f"VirtualDut backend failed: {error}",
                    ConstraintScope.VIRTUAL_DUT,
                ),
            )
        return DutTransition(
            FunctionBackendState(
                state.received + 1, state.emitted + len(emissions)
            ),
            emissions,
        )
