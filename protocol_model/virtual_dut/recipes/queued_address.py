"""Assembly of an explicitly advanced queued address responder."""

from __future__ import annotations

from typing import Mapping

from protocol_model.semantics import ResourceExhaustionPolicy

from ..backend.queued_address import (
    AddressDelayPolicy,
    QueuedAddressResponderBackend,
)
from ..address.target import AddressTarget
from ..binding.builder import VirtualDutBuilder
from ..binding.port import InterfaceAttachmentBinding
from ..boundary.module import DutBehaviorTag, VirtualDut


def build_queued_address_responder_vdut(
    name: str,
    handler: AddressTarget,
    bindings: Mapping[str, InterfaceAttachmentBinding],
    *,
    capacity: int,
    delay_policy: AddressDelayPolicy,
    exhaustion_policy: ResourceExhaustionPolicy | str = (
        ResourceExhaustionPolicy.BLOCK
    ),
    description: str = "explicitly advanced queued address responder",
) -> VirtualDut:
    """Assemble selected address completers around the queued backend."""

    binding_by_name = dict(bindings)
    backend = QueuedAddressResponderBackend(
        handler,
        binding_by_name,
        capacity=capacity,
        delay_policy=delay_policy,
        exhaustion_policy=exhaustion_policy,
    )
    builder = (
        VirtualDutBuilder(name)
        .with_backend(backend)
        .with_behavior_tags(DutBehaviorTag.ADDRESSABLE)
        .describe(description)
    )
    for binding in binding_by_name.values():
        builder.bind(binding)
    return builder.build()


__all__ = ["build_queued_address_responder_vdut"]
