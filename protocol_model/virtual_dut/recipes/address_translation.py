"""Recipe for a two-port typed address translation VirtualDut."""

from __future__ import annotations

from ..attachments.address import AddressCompleterAttachment
from ..attachments.address_operation import (
    AddressAccessOperationAdapter,
    AddressOperationCompleterAttachment,
)
from ..binding.builder import VirtualDutBuilder
from ..binding.port import InterfaceAttachmentBinding
from ..boundary.module import DutBehaviorTag, VirtualDut
from ..translation.address_operation_backend import (
    AddressOperationTranslationBridgeBackend,
)
from ..translation.engine import SerialTranslationExecutor


def build_address_translation_vdut(
    name: str,
    ingress: InterfaceAttachmentBinding,
    egress: InterfaceAttachmentBinding,
    executor: SerialTranslationExecutor,
    *,
    description: str = "typed serial address translation bridge",
) -> VirtualDut:
    """Assemble a single-access ingress around the shared operation backend.

    Protocol-specific integration code chooses the two attachments and builds
    the translation plan.  A narrow same-domain adapter presents the existing
    ``AddressCompleterAttachment`` as an operation codec, so a single access
    and a burst use the same cross-port owner/scheduler implementation.
    """

    if not isinstance(ingress.attachment, AddressCompleterAttachment):
        raise TypeError(
            "single-access address translation requires an address completer"
        )
    operation_ingress = InterfaceAttachmentBinding(
        ingress.port,
        AddressAccessOperationAdapter(
            ingress.attachment, executor.plan.source
        ),
    )
    return build_address_operation_translation_vdut(
        name,
        operation_ingress,
        egress,
        executor,
        description=description,
    )


def build_address_operation_translation_vdut(
    name: str,
    ingress: InterfaceAttachmentBinding,
    egress: InterfaceAttachmentBinding,
    executor: SerialTranslationExecutor,
    *,
    description: str = "typed serial address-operation translation bridge",
) -> VirtualDut:
    """Assemble an address-domain operation codec and access requester."""

    if not isinstance(
        ingress.attachment, AddressOperationCompleterAttachment
    ):
        raise TypeError(
            "address operation translation requires an operation completer"
        )
    backend = AddressOperationTranslationBridgeBackend(
        ingress, egress, executor
    )
    return (
        VirtualDutBuilder(name)
        .bind(ingress)
        .bind(egress)
        .with_backend(backend)
        .with_behavior_tags(DutBehaviorTag.TRANSFORMING, DutBehaviorTag.ROUTING)
        .describe(description)
        .build()
    )


__all__ = [
    "build_address_operation_translation_vdut",
    "build_address_translation_vdut",
]
