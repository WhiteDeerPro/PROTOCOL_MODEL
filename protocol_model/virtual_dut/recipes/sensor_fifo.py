"""Assembly of a protocol-independent address-visible sensor FIFO."""

from __future__ import annotations

from ..backend.sensor_fifo import (
    SensorFifoBackend,
    SensorFifoConfig,
    SensorSamplePolicy,
)
from ..binding.builder import VirtualDutBuilder
from ..binding.port import InterfaceAttachmentBinding
from ..boundary.module import DutBehaviorTag, VirtualDut


def build_sensor_fifo_vdut(
    name: str,
    binding: InterfaceAttachmentBinding,
    config: SensorFifoConfig,
    sample_policy: SensorSamplePolicy,
    *,
    description: str = "explicitly serviced address-visible sensor FIFO",
) -> VirtualDut:
    """Bind one address completer around a finite sample FIFO backend."""

    backend = SensorFifoBackend(binding, config, sample_policy)
    return (
        VirtualDutBuilder(name)
        .bind(binding)
        .with_backend(backend)
        .with_behavior_tags(DutBehaviorTag.ADDRESSABLE)
        .describe(description)
        .build()
    )


__all__ = ["build_sensor_fifo_vdut"]
