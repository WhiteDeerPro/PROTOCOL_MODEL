"""Constructed backend that captures accepted stream transfers."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import ConstraintScope, SemanticFault

from ..attachments.stream import StreamReceiverAttachment, StreamTransfer
from ..binding.port import PortAttachmentBinding
from .base import VirtualDutModel
from .transition import DutTransition, PortInput


@dataclass(frozen=True)
class CapturedStreamTransfer:
    port: str
    transfer: StreamTransfer


@dataclass(frozen=True)
class StreamCaptureState:
    attachment_states: Mapping[str, object]
    captured: tuple[CapturedStreamTransfer, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attachment_states",
            MappingProxyType(dict(self.attachment_states)),
        )


class StreamCaptureBackend(VirtualDutModel):
    """Protocol-neutral sink fixture retaining decoded transfers in order."""

    def __init__(
        self, bindings: Mapping[str, PortAttachmentBinding]
    ) -> None:
        bindings = dict(bindings)
        if not bindings:
            raise ValueError("stream capture backend requires a binding")
        if any(
            not isinstance(item, PortAttachmentBinding)
            for item in bindings.values()
        ):
            raise TypeError("stream capture backend requires attachment bindings")
        if set(bindings) != {item.name for item in bindings.values()}:
            raise ValueError("stream capture binding keys must match port names")
        if any(
            not isinstance(item.attachment, StreamReceiverAttachment)
            for item in bindings.values()
        ):
            raise TypeError("stream capture backend requires receiver bindings")
        self.bindings = MappingProxyType(bindings)
        self.attachments = MappingProxyType(
            {
                name: binding.attachment
                for name, binding in bindings.items()
            }
        )

    def local_attachment_bindings(
        self,
    ) -> Mapping[str, PortAttachmentBinding]:
        return self.bindings

    def initial_state(self) -> StreamCaptureState:
        return StreamCaptureState(
            {
                name: attachment.initial_state()
                for name, attachment in self.attachments.items()
            }
        )

    def accept(self, state: object, action: PortInput) -> DutTransition:
        if not isinstance(state, StreamCaptureState):
            raise TypeError("StreamCaptureBackend requires StreamCaptureState")
        attachment = self.attachments.get(action.port)
        if attachment is None:
            return DutTransition(
                state,
                fault=SemanticFault(
                    "stream_capture.unknown_port",
                    f"no stream receiver is bound to port {action.port!r}",
                    ConstraintScope.VIRTUAL_DUT,
                ),
            )
        decoded = attachment.decode_transfer(
            state.attachment_states[action.port], action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)
        attachment_states = dict(state.attachment_states)
        attachment_states[action.port] = decoded.state
        captured = state.captured
        if decoded.transfer is not None:
            captured = captured + (
                CapturedStreamTransfer(action.port, decoded.transfer),
            )
        return DutTransition(StreamCaptureState(attachment_states, captured))

    def is_quiescent(self, state: object) -> bool:
        return isinstance(state, StreamCaptureState) and all(
            attachment.is_quiescent(state.attachment_states[name])
            for name, attachment in self.attachments.items()
        )
