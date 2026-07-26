"""Assembly of a serialized protocol-independent memory-copy requester."""

from __future__ import annotations

from ..backend.memory_copy import (
    MemoryCopyDescriptor,
    SerializedMemoryCopyBackend,
)
from ..binding.builder import VirtualDutBuilder
from ..binding.port import InterfaceAttachmentBinding
from ..boundary.module import DutBehaviorTag, VirtualDut


def build_serialized_memory_copy_vdut(
    name: str,
    binding: InterfaceAttachmentBinding,
    descriptor: MemoryCopyDescriptor,
    *,
    description: str = "serialized single-outstanding memory-copy engine",
) -> VirtualDut:
    """Bind one address requester around a fixed memory-copy descriptor."""

    backend = SerializedMemoryCopyBackend(binding, descriptor)
    return (
        VirtualDutBuilder(name)
        .bind(binding)
        .with_backend(backend)
        .with_behavior_tags(DutBehaviorTag.INITIATING)
        .describe(description)
        .build()
    )


__all__ = ["build_serialized_memory_copy_vdut"]
