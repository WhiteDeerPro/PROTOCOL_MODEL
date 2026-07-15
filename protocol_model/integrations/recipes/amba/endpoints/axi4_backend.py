"""Constructed backend for a burst-aware AXI4 AddressSpace endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import ConstraintScope, SemanticFault
from protocol_model.virtual_dut.address.space import AddressSpace, AddressSpaceState
from protocol_model.virtual_dut.backend.base import VirtualDutModel
from protocol_model.virtual_dut.backend.transition import (
    DutTransition,
    PortEmission,
    PortInput,
)
from protocol_model.virtual_dut.binding.port import PortAttachmentBinding

from protocol_model.integrations.attachments.amba.axi.axi4 import (
    Axi4AddressSpaceAttachment,
)


@dataclass(frozen=True)
class Axi4AddressSpaceBackendState:
    address_space: AddressSpaceState
    attachment_state: object


class Axi4AddressSpaceBackend(VirtualDutModel):
    """Execute all beats of one accepted AXI4 burst synchronously.

    Individual beats remain ordinary AddressAccess operations. Successful
    writes before a later error are retained, because an AXI burst is not an
    atomic memory transaction. Register effects are still rejected at this
    passive endpoint boundary.
    """

    def __init__(
        self,
        address_space: AddressSpace,
        binding: PortAttachmentBinding,
    ) -> None:
        if not isinstance(binding, PortAttachmentBinding):
            raise TypeError("AXI4 AddressSpace backend requires an attachment binding")
        if not isinstance(binding.attachment, Axi4AddressSpaceAttachment):
            raise TypeError(
                "AXI4 AddressSpace backend requires Axi4AddressSpaceAttachment"
            )
        self.address_space = address_space
        self.binding = binding
        self.attachment = binding.attachment
        self.bindings = MappingProxyType({binding.name: binding})

    def local_attachment_bindings(
        self,
    ) -> Mapping[str, PortAttachmentBinding]:
        return self.bindings

    def initial_state(self) -> Axi4AddressSpaceBackendState:
        return Axi4AddressSpaceBackendState(
            self.address_space.initial_state(),
            self.attachment.initial_state(),
        )

    def accept(self, state: object, action: PortInput) -> DutTransition:
        if not isinstance(state, Axi4AddressSpaceBackendState):
            raise TypeError(
                "Axi4AddressSpaceBackend requires Axi4AddressSpaceBackendState"
            )
        if action.port != self.binding.name:
            return DutTransition(
                state,
                fault=self._fault(
                    "unknown_port",
                    f"AXI4 AddressSpace endpoint has no port {action.port!r}",
                ),
            )

        decoded = self.attachment.decode_request(
            state.attachment_state, action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)
        if decoded.request is None:
            return DutTransition(
                Axi4AddressSpaceBackendState(
                    state.address_space, decoded.state
                )
            )

        address_state = state.address_space
        results = []
        for access in decoded.request.accesses:
            accessed = self.address_space.access(address_state, access)
            if accessed.result.effects:
                return DutTransition(
                    state,
                    fault=self._fault(
                        "unhandled_effect",
                        "passive AXI4 AddressSpace endpoint cannot consume "
                        "register effects",
                    ),
                )
            address_state = accessed.state
            results.append(accessed.result)

        encoded = self.attachment.encode_completion(
            decoded.state, decoded.request, tuple(results)
        )
        if encoded.fault is not None:
            return DutTransition(state, fault=encoded.fault)
        return DutTransition(
            Axi4AddressSpaceBackendState(address_state, encoded.state),
            tuple(
                PortEmission(self.binding.name, event)
                for event in encoded.events
            ),
        )

    def is_quiescent(self, state: object) -> bool:
        return (
            isinstance(state, Axi4AddressSpaceBackendState)
            and self.attachment.is_quiescent(state.attachment_state)
        )

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"axi4_address_space_backend.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )
