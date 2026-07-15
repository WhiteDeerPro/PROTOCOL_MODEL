"""Constructed backend that serves a passive local AddressSpace."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import ConstraintScope, SemanticFault

from ..address.space import AddressSpace, AddressSpaceState
from ..attachments.address import AddressCompleterAttachment
from ..binding.port import PortAttachmentBinding
from .base import VirtualDutModel
from .transition import DutTransition, PortEmission, PortInput


@dataclass(frozen=True)
class AddressSpaceBackendState:
    address_space: AddressSpaceState
    attachment_states: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attachment_states",
            MappingProxyType(dict(self.attachment_states)),
        )


class PassiveAddressSpaceBackend(VirtualDutModel):
    """Endpoint backend with no autonomous or unhandled internal effects."""

    def __init__(
        self,
        address_space: AddressSpace,
        bindings: Mapping[str, PortAttachmentBinding],
    ) -> None:
        bindings = dict(bindings)
        if not bindings:
            raise ValueError("passive address-space backend requires a binding")
        if any(
            not isinstance(item, PortAttachmentBinding)
            for item in bindings.values()
        ):
            raise TypeError(
                "passive address-space backend requires attachment bindings"
            )
        if set(bindings) != {item.name for item in bindings.values()}:
            raise ValueError("address-space binding keys must match port names")
        if any(
            not isinstance(item.attachment, AddressCompleterAttachment)
            for item in bindings.values()
        ):
            raise TypeError(
                "passive address-space backend requires completer bindings"
            )
        self.address_space = address_space
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

    def initial_state(self) -> AddressSpaceBackendState:
        return AddressSpaceBackendState(
            self.address_space.initial_state(),
            {
                name: attachment.initial_state()
                for name, attachment in self.attachments.items()
            },
        )

    def accept(self, state: object, action: PortInput) -> DutTransition:
        if not isinstance(state, AddressSpaceBackendState):
            raise TypeError(
                "PassiveAddressSpaceBackend requires AddressSpaceBackendState"
            )
        attachment = self.attachments.get(action.port)
        if attachment is None:
            return DutTransition(
                state,
                fault=SemanticFault(
                    "address_space_backend.unknown_port",
                    f"no address-space attachment is bound to port {action.port!r}",
                    ConstraintScope.VIRTUAL_DUT,
                ),
            )
        decoded = attachment.decode_request(
            state.attachment_states[action.port], action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)
        if decoded.access is None:
            attachment_states = dict(state.attachment_states)
            attachment_states[action.port] = decoded.state
            return DutTransition(
                AddressSpaceBackendState(state.address_space, attachment_states)
            )
        accessed = self.address_space.access(state.address_space, decoded.access)
        if accessed.result.effects:
            return DutTransition(
                state,
                fault=SemanticFault(
                    "address_space_backend.unhandled_effect",
                    "passive address-space backend cannot consume register effects",
                    ConstraintScope.VIRTUAL_DUT,
                ),
            )
        encoded = attachment.encode_completion(
            decoded.state, decoded.reply_context, accessed.result
        )
        if encoded.fault is not None:
            return DutTransition(state, fault=encoded.fault)
        attachment_states = dict(state.attachment_states)
        attachment_states[action.port] = encoded.state
        return DutTransition(
            AddressSpaceBackendState(accessed.state, attachment_states),
            tuple(PortEmission(action.port, event) for event in encoded.events),
        )

    def is_quiescent(self, state: object) -> bool:
        if not isinstance(state, AddressSpaceBackendState):
            return False
        return all(
            attachment.is_quiescent(state.attachment_states[name])
            for name, attachment in self.attachments.items()
        )
