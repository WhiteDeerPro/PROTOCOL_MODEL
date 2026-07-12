"""Construction contract for functional verification nodes, not RTL models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

from protocol_model.core import SemanticComponent


InputT = TypeVar("InputT")
StateT = TypeVar("StateT")
OutputT = TypeVar("OutputT")


class VirtualDutKind(str, Enum):
    SOURCE = "source"
    SINK = "sink"
    RESPONDER = "responder"
    TRANSFORM = "transform"
    PROXY = "proxy"


@dataclass(frozen=True)
class VirtualDutContract:
    """Executable-model intent and audit metadata."""

    assumptions: tuple[str, ...] = ()
    guarantees: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()


@dataclass(frozen=True)
class VirtualDutDescriptor:
    name: str
    kind: VirtualDutKind
    implementation: str
    capabilities: frozenset[str]
    contract: VirtualDutContract


class VirtualDut(
    SemanticComponent[InputT, StateT, OutputT],
    Generic[InputT, StateT, OutputT],
):
    """A functional action strategy with state and owned outputs.

    A VirtualDut is not an RTL implementation. It can be an executable Python
    model, a C/C++ proxy, a scripted endpoint, or a stateful bridge. Protocol
    components constrain its port behavior; Projects connect it to links.
    """

    kind: VirtualDutKind
    capabilities: frozenset[str] = frozenset()
    contract: VirtualDutContract = VirtualDutContract()

    @property
    def descriptor(self) -> VirtualDutDescriptor:
        return VirtualDutDescriptor(
            self.name,
            self.kind,
            type(self).__name__,
            self.capabilities,
            self.contract,
        )
