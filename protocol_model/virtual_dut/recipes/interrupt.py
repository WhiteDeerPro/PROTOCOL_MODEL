"""Assembly recipes for protocol-neutral interrupt behavior cores."""

from __future__ import annotations

from typing import Mapping

from protocol_model.semantics import ResourceExhaustionPolicy

from ..backend.interrupt import (
    ExplicitEoiInterruptTargetBackend,
    PriorityInterruptControllerBackend,
)
from ..binding.builder import VirtualDutBuilder
from ..binding.port import InterfaceAttachmentBinding
from ..boundary.module import DutBehaviorTag, VirtualDut


def build_priority_interrupt_controller_vdut(
    name: str,
    ingress_bindings: Mapping[str, InterfaceAttachmentBinding],
    target_binding: InterfaceAttachmentBinding,
    *,
    capacity: int,
    exhaustion_policy: ResourceExhaustionPolicy | str = (
        ResourceExhaustionPolicy.BLOCK
    ),
    description: str = "priority edge-interrupt collector",
) -> VirtualDut:
    """Place notification attachments around one controller backend."""

    ingress_bindings = dict(ingress_bindings)
    backend = PriorityInterruptControllerBackend(
        ingress_bindings,
        target_binding,
        capacity=capacity,
        exhaustion_policy=exhaustion_policy,
    )
    builder = (
        VirtualDutBuilder(name)
        .with_backend(backend)
        .with_behavior_tags(DutBehaviorTag.ROUTING, DutBehaviorTag.SIGNALING)
        .describe(description)
    )
    for binding in (*ingress_bindings.values(), target_binding):
        builder.bind(binding)
    return builder.build()


def build_explicit_eoi_interrupt_target_vdut(
    name: str,
    binding: InterfaceAttachmentBinding,
    *,
    description: str = "single-active interrupt target with explicit EOI",
) -> VirtualDut:
    """Build a small target fixture whose advance action emits one EOI."""

    backend = ExplicitEoiInterruptTargetBackend(binding)
    return (
        VirtualDutBuilder(name)
        .bind(binding)
        .with_backend(backend)
        .with_behavior_tags(DutBehaviorTag.SIGNALING)
        .describe(description)
        .build()
    )


__all__ = [
    "build_explicit_eoi_interrupt_target_vdut",
    "build_priority_interrupt_controller_vdut",
]
