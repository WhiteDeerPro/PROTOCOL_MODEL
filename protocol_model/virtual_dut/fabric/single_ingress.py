"""Single-ingress address routing backend."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import ConstraintScope, SemanticFault

from ..address.access import AccessResult, AccessStatus
from ..attachments.address import (
    AddressCompleterAttachment,
    AddressRequest,
    AddressRequesterAttachment,
)
from ..backend.base import VirtualDutModel
from ..backend.transition import DutTransition, PortEmission, PortInput
from ..binding.port import PortAttachmentBinding
from .route import AddressRoute, validate_address_routes
from .state import AddressFabricState, RoutedAddressRequest


class SingleIngressAddressFabricBackend(VirtualDutModel):
    """Synchronous one-ingress address decoder and completion mux.

    This execution profile intentionally has one active cross-port request.
    It provides the first decoder/bridge building block without claiming
    multi-ingress arbitration, deferred emission, or network-level closure.
    """

    def __init__(
        self,
        ingress_binding: PortAttachmentBinding,
        egress_bindings: Mapping[str, PortAttachmentBinding],
        routes: tuple[AddressRoute, ...],
    ) -> None:
        if not isinstance(ingress_binding, PortAttachmentBinding):
            raise TypeError("fabric ingress requires an attachment binding")
        ingress_port = ingress_binding.name
        ingress_attachment = ingress_binding.attachment
        if not isinstance(ingress_attachment, AddressCompleterAttachment):
            raise TypeError("fabric ingress requires a completer binding")
        egress_bindings = dict(egress_bindings)
        if any(
            not isinstance(item, PortAttachmentBinding)
            for item in egress_bindings.values()
        ):
            raise TypeError("fabric egresses require attachment bindings")
        if set(egress_bindings) != {
            item.name for item in egress_bindings.values()
        }:
            raise ValueError("fabric egress binding keys must match port names")
        egress = {
            name: binding.attachment
            for name, binding in egress_bindings.items()
        }
        if not egress:
            raise ValueError("address fabric requires at least one egress")
        if ingress_port in egress:
            raise ValueError("fabric ingress and egress port names must differ")
        if any(
            not name or not isinstance(item, AddressRequesterAttachment)
            for name, item in egress.items()
        ):
            raise TypeError("fabric egresses require requester bindings")

        self.ingress_port = ingress_port
        self.ingress_binding = ingress_binding
        self.ingress_attachment = ingress_attachment
        self.egress_bindings = MappingProxyType(egress_bindings)
        self.egress_attachments = MappingProxyType(egress)
        self.bindings = MappingProxyType(
            {ingress_binding.name: ingress_binding, **egress_bindings}
        )
        self.routes = validate_address_routes(routes, egress)

    def local_attachment_bindings(
        self,
    ) -> Mapping[str, PortAttachmentBinding]:
        return self.bindings

    def initial_state(self) -> AddressFabricState:
        return AddressFabricState(
            self.ingress_attachment.initial_state(),
            {
                name: attachment.initial_state()
                for name, attachment in self.egress_attachments.items()
            },
            {},
        )

    def accept(self, state: object, action: PortInput) -> DutTransition:
        if not isinstance(state, AddressFabricState):
            raise TypeError(
                "SingleIngressAddressFabricBackend requires AddressFabricState"
            )
        if action.port == self.ingress_port:
            return self._accept_ingress(state, action)
        if action.port in self.egress_attachments:
            return self._accept_egress(state, action)
        return DutTransition(
            state,
            fault=self._fault(
                "unknown_port", f"fabric has no port {action.port!r}"
            ),
        )

    def _accept_ingress(
        self, state: AddressFabricState, action: PortInput
    ) -> DutTransition:
        if state.pending:
            return DutTransition(
                state,
                fault=self._fault(
                    "busy",
                    "single-ingress fabric already owns an active request",
                ),
            )

        decoded = self.ingress_attachment.decode_request(
            state.ingress_state, action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)
        if decoded.access is None:
            return DutTransition(
                AddressFabricState(
                    decoded.state,
                    state.egress_states,
                    state.pending,
                    state.next_request_id,
                )
            )

        route = next(
            (item for item in self.routes if item.contains(decoded.access)),
            None,
        )
        if route is None:
            encoded = self.ingress_attachment.encode_completion(
                decoded.state,
                decoded.reply_context,
                AccessResult(status=AccessStatus.DECODE_ERROR),
            )
            if encoded.fault is not None:
                return DutTransition(state, fault=encoded.fault)
            return DutTransition(
                AddressFabricState(
                    encoded.state,
                    state.egress_states,
                    state.pending,
                    state.next_request_id,
                ),
                tuple(
                    PortEmission(self.ingress_port, event)
                    for event in encoded.events
                ),
            )

        request_id = state.next_request_id
        output_access = route.translate(decoded.access)
        requester = self.egress_attachments[route.egress_port]
        encoded = requester.encode_request(
            state.egress_states[route.egress_port],
            AddressRequest(request_id, output_access),
        )
        if encoded.fault is not None:
            return DutTransition(state, fault=encoded.fault)

        egress_states = dict(state.egress_states)
        egress_states[route.egress_port] = encoded.state
        pending = dict(state.pending)
        pending[request_id] = RoutedAddressRequest(
            request_id,
            self.ingress_port,
            route.egress_port,
            decoded.access,
            output_access,
            decoded.reply_context,
        )
        return DutTransition(
            AddressFabricState(
                decoded.state,
                egress_states,
                pending,
                request_id + 1,
            ),
            tuple(
                PortEmission(route.egress_port, event)
                for event in encoded.events
            ),
        )

    def _accept_egress(
        self, state: AddressFabricState, action: PortInput
    ) -> DutTransition:
        attachment = self.egress_attachments[action.port]
        decoded = attachment.decode_completion(
            state.egress_states[action.port], action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)

        egress_states = dict(state.egress_states)
        egress_states[action.port] = decoded.state
        if decoded.completion is None:
            return DutTransition(
                AddressFabricState(
                    state.ingress_state,
                    egress_states,
                    state.pending,
                    state.next_request_id,
                )
            )

        completion = decoded.completion
        pending_request = state.pending.get(completion.request_id)
        if pending_request is None:
            return DutTransition(
                state,
                fault=self._fault(
                    "unknown_completion",
                    f"no request owns completion {completion.request_id}",
                ),
            )
        if pending_request.egress_port != action.port:
            return DutTransition(
                state,
                fault=self._fault(
                    "completion_port",
                    f"completion {completion.request_id} arrived on {action.port!r}, "
                    f"not {pending_request.egress_port!r}",
                ),
            )
        if completion.result.effects:
            return DutTransition(
                state,
                fault=self._fault(
                    "completion_effect",
                    "this address fabric completion boundary does not carry "
                    "endpoint-local effects",
                ),
            )

        encoded = self.ingress_attachment.encode_completion(
            state.ingress_state,
            pending_request.reply_context,
            completion.result,
        )
        if encoded.fault is not None:
            return DutTransition(state, fault=encoded.fault)
        pending = dict(state.pending)
        del pending[completion.request_id]
        return DutTransition(
            AddressFabricState(
                encoded.state,
                egress_states,
                pending,
                state.next_request_id,
            ),
            tuple(
                PortEmission(pending_request.ingress_port, event)
                for event in encoded.events
            ),
        )

    def is_quiescent(self, state: object) -> bool:
        if not isinstance(state, AddressFabricState):
            return False
        return (
            not state.pending
            and self.ingress_attachment.is_quiescent(state.ingress_state)
            and all(
                attachment.is_quiescent(state.egress_states[name])
                for name, attachment in self.egress_attachments.items()
            )
        )

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"address_fabric.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )
