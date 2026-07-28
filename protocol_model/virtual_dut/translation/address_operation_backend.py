"""Serial typed-operation translation with an address-request egress."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import ConstraintScope, SemanticFault

from ..address.access import AccessResult, AddressRead, AddressWrite
from ..attachments.address import (
    AddressRequest,
    AddressRequesterAttachment,
)
from ..attachments.address_operation import (
    AddressOperationCompleterAttachment,
)
from ..backend.base import VirtualDutBackend
from ..backend.transition import DutTransition, PortEmission, PortInput
from ..binding.port import InterfaceAttachmentBinding
from .engine import (
    CompleteParent,
    IssueChild,
    SerialTranslationExecutor,
    SerialTranslationState,
)
from .envelope import DecodedOperation
from .lifecycle import ChildOwner


@dataclass(frozen=True)
class AddressOperationTranslationState:
    """Atomic snapshot of ingress, egress, executor, and child ownership."""

    ingress_state: object
    egress_state: object
    translation_state: SerialTranslationState
    pending_children: Mapping[int, ChildOwner] = field(default_factory=dict)

    def __post_init__(self) -> None:
        pending = dict(self.pending_children)
        if any(
            not isinstance(request_id, int)
            or isinstance(request_id, bool)
            or request_id < 0
            or not isinstance(owner, ChildOwner)
            for request_id, owner in pending.items()
        ):
            raise TypeError(
                "address translation pending children require non-negative "
                "integer ids and ChildOwner values"
            )
        object.__setattr__(
            self, "pending_children", MappingProxyType(pending)
        )


class AddressOperationTranslationBridgeBackend(VirtualDutBackend):
    """Execute one typed address-domain parent against address-access children.

    The constructed VirtualDut deliberately exposes the serial executor's
    scheduling and capacity choices.  When the subject is external RTL rather
    than this constructed module, conformance should target the selected
    bridge contract instead of requiring equality with one generated trace.

    The source operation may be a single access or a grouped form such as
    ``AddressBurst``.  Its ingress attachment owns port-local assembly and
    reply encoding; the existing serial executor owns fan-out, lineage,
    capacity, and completion folding.  The egress remains the established
    ``AddressRequesterAttachment`` contract.
    """

    def __init__(
        self,
        ingress_binding: InterfaceAttachmentBinding,
        egress_binding: InterfaceAttachmentBinding,
        executor: SerialTranslationExecutor,
    ) -> None:
        if not isinstance(ingress_binding, InterfaceAttachmentBinding):
            raise TypeError(
                "address operation ingress requires an attachment binding"
            )
        if not isinstance(egress_binding, InterfaceAttachmentBinding):
            raise TypeError(
                "address operation egress requires an attachment binding"
            )
        if not isinstance(
            ingress_binding.attachment,
            AddressOperationCompleterAttachment,
        ):
            raise TypeError(
                "address operation ingress requires an operation completer"
            )
        if not isinstance(
            egress_binding.attachment, AddressRequesterAttachment
        ):
            raise TypeError(
                "address operation egress requires an address requester"
            )
        if ingress_binding.name == egress_binding.name:
            raise ValueError(
                "address operation ingress and egress ports must differ"
            )
        if not isinstance(executor, SerialTranslationExecutor):
            raise TypeError(
                "address operation backend requires a serial executor"
            )

        ingress_attachment = ingress_binding.attachment
        if executor.plan.source != ingress_attachment.operation_signature:
            raise ValueError(
                "translation source signature must match the ingress codec"
            )
        target = executor.plan.target
        if set(target.request_types) != {AddressRead, AddressWrite} or (
            target.completion_types != (AccessResult,)
        ):
            raise ValueError(
                "address operation target must use address read/write and "
                "AccessResult"
            )
        if executor.profile.egress_binding != egress_binding.name:
            raise ValueError(
                "serial executor egress binding must match the bridge port"
            )

        self.ingress_binding = ingress_binding
        self.egress_binding = egress_binding
        self.ingress_port = ingress_binding.name
        self.egress_port = egress_binding.name
        self.ingress_attachment = ingress_attachment
        self.egress_attachment = egress_binding.attachment
        self.executor = executor
        self.bindings = MappingProxyType(
            {
                self.ingress_port: ingress_binding,
                self.egress_port: egress_binding,
            }
        )

    def local_attachment_bindings(
        self,
    ) -> Mapping[str, InterfaceAttachmentBinding]:
        return self.bindings

    def initial_state(self) -> AddressOperationTranslationState:
        return AddressOperationTranslationState(
            self.ingress_attachment.initial_state(),
            self.egress_attachment.initial_state(),
            self.executor.initial_state(),
        )

    def accept(self, state: object, action: PortInput) -> DutTransition:
        if not isinstance(state, AddressOperationTranslationState):
            raise TypeError(
                "AddressOperationTranslationBridgeBackend requires "
                "AddressOperationTranslationState"
            )
        if action.port == self.ingress_port:
            return self._accept_ingress(state, action)
        if action.port == self.egress_port:
            return self._accept_egress(state, action)
        return DutTransition(
            state,
            fault=self._fault(
                "unknown_port",
                f"address operation bridge has no port {action.port!r}",
            ),
        )

    def is_quiescent(self, state: object) -> bool:
        return (
            isinstance(state, AddressOperationTranslationState)
            and not state.pending_children
            and self.ingress_attachment.is_quiescent(state.ingress_state)
            and self.egress_attachment.is_quiescent(state.egress_state)
            and self.executor.is_quiescent(state.translation_state)
        )

    def _accept_ingress(
        self,
        original: AddressOperationTranslationState,
        action: PortInput,
    ) -> DutTransition:
        decoded = self.ingress_attachment.decode_operation(
            original.ingress_state, action.event
        )
        if decoded.fault is not None:
            return DutTransition(original, fault=decoded.fault)
        candidate = replace(original, ingress_state=decoded.state)
        if decoded.operation is None:
            return DutTransition(candidate)
        if not self.executor.plan.source.accepts_request(decoded.operation):
            return DutTransition(
                original,
                fault=self._fault(
                    "parent_type",
                    "ingress codec emitted an operation outside its signature",
                ),
            )

        transition = self.executor.accept_parent(
            candidate.translation_state,
            DecodedOperation(decoded.operation, decoded.reply_context),
            ingress_binding=self.ingress_port,
        )
        if transition.fault is not None:
            return DutTransition(original, fault=transition.fault)
        candidate = replace(
            candidate, translation_state=transition.state
        )
        return self._encode_translation_emissions(
            original, candidate, transition.emissions
        )

    def _accept_egress(
        self,
        original: AddressOperationTranslationState,
        action: PortInput,
    ) -> DutTransition:
        decoded = self.egress_attachment.decode_completion(
            original.egress_state, action.event
        )
        if decoded.fault is not None:
            return DutTransition(original, fault=decoded.fault)
        candidate = replace(original, egress_state=decoded.state)
        if decoded.completion is None:
            return DutTransition(candidate)

        request_id = decoded.completion.request_id
        owner = candidate.pending_children.get(request_id)
        if owner is None:
            return DutTransition(
                original,
                fault=self._fault(
                    "completion_owner",
                    f"downstream completion {request_id} has no child owner",
                ),
            )
        pending = dict(candidate.pending_children)
        del pending[request_id]
        transition = self.executor.accept_child_completion(
            candidate.translation_state,
            owner,
            decoded.completion.result,
        )
        if transition.fault is not None:
            return DutTransition(original, fault=transition.fault)
        candidate = replace(
            candidate,
            translation_state=transition.state,
            pending_children=pending,
        )
        return self._encode_translation_emissions(
            original, candidate, transition.emissions
        )

    def _encode_translation_emissions(
        self,
        original: AddressOperationTranslationState,
        candidate: AddressOperationTranslationState,
        translation_emissions: tuple[object, ...],
    ) -> DutTransition:
        port_emissions: list[PortEmission] = []
        pending = dict(candidate.pending_children)
        ingress_state = candidate.ingress_state
        egress_state = candidate.egress_state

        for emission in translation_emissions:
            if isinstance(emission, IssueChild):
                if emission.owner.egress_binding != self.egress_port:
                    return DutTransition(
                        original,
                        fault=self._fault(
                            "egress_binding",
                            "translation child selected another egress binding",
                        ),
                    )
                if not isinstance(
                    emission.operation, (AddressRead, AddressWrite)
                ):
                    return DutTransition(
                        original,
                        fault=self._fault(
                            "child_type",
                            "address translation emitted a non-address child",
                        ),
                    )
                request_id = emission.owner.lineage.child.serial
                if request_id in pending:
                    return DutTransition(
                        original,
                        fault=self._fault(
                            "child_id",
                            f"duplicate downstream child id {request_id}",
                        ),
                    )
                encoded = self.egress_attachment.encode_request(
                    egress_state,
                    AddressRequest(request_id, emission.operation),
                )
                if encoded.fault is not None:
                    return DutTransition(original, fault=encoded.fault)
                egress_state = encoded.state
                pending[request_id] = emission.owner
                port_emissions.extend(
                    PortEmission(self.egress_port, event)
                    for event in encoded.events
                )
                continue

            if isinstance(emission, CompleteParent):
                if emission.envelope.ingress_binding != self.ingress_port:
                    return DutTransition(
                        original,
                        fault=self._fault(
                            "ingress_binding",
                            "translation completion selected another ingress",
                        ),
                    )
                if not self.executor.plan.source.accepts_completion(
                    emission.result
                ):
                    return DutTransition(
                        original,
                        fault=self._fault(
                            "parent_result_type",
                            "translation returned an invalid parent result",
                        ),
                    )
                encoded = (
                    self.ingress_attachment.encode_operation_completion(
                        ingress_state,
                        emission.envelope.reply_context,
                        emission.result,
                    )
                )
                if encoded.fault is not None:
                    return DutTransition(original, fault=encoded.fault)
                ingress_state = encoded.state
                port_emissions.extend(
                    PortEmission(self.ingress_port, event)
                    for event in encoded.events
                )
                continue

            return DutTransition(
                original,
                fault=self._fault(
                    "translation_emission",
                    "unsupported translation emission "
                    f"{type(emission).__name__}",
                ),
            )

        committed = replace(
            candidate,
            ingress_state=ingress_state,
            egress_state=egress_state,
            pending_children=pending,
        )
        return DutTransition(committed, tuple(port_emissions))

    @staticmethod
    def _fault(suffix: str, reason: str) -> SemanticFault:
        return SemanticFault(
            f"address_operation_bridge.{suffix}",
            reason,
            ConstraintScope.VIRTUAL_DUT,
        )


__all__ = [
    "AddressOperationTranslationBridgeBackend",
    "AddressOperationTranslationState",
]
