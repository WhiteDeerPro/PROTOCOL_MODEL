"""Assembly of a scheduled protocol-independent address crossbar."""

from __future__ import annotations

from typing import Mapping

from protocol_model.semantics import ResourceExhaustionPolicy

from ..binding.builder import VirtualDutBuilder
from ..binding.port import InterfaceAttachmentBinding
from ..boundary.module import DutBehaviorTag, VirtualDut
from ..fabric.crossbar import ScheduledAddressCrossbarBackend
from ..fabric.route import AddressRoute


def build_scheduled_address_crossbar_vdut(
    name: str,
    ingress_ports: Mapping[str, InterfaceAttachmentBinding],
    egress_ports: Mapping[str, InterfaceAttachmentBinding],
    routes: tuple[AddressRoute, ...],
    *,
    ingress_queue_capacity: int,
    exhaustion_policy: ResourceExhaustionPolicy | str = (
        ResourceExhaustionPolicy.BLOCK
    ),
    description: str = "scheduled single-access address crossbar",
) -> VirtualDut:
    """Bind address codecs around the shared N-ingress/M-egress backend."""

    ingress_bindings = dict(ingress_ports)
    egress_bindings = dict(egress_ports)
    backend = ScheduledAddressCrossbarBackend(
        ingress_bindings,
        egress_bindings,
        routes,
        ingress_queue_capacity=ingress_queue_capacity,
        exhaustion_policy=exhaustion_policy,
    )
    builder = (
        VirtualDutBuilder(name)
        .with_backend(backend)
        .with_behavior_tags(DutBehaviorTag.ROUTING)
        .describe(description)
    )
    for binding in ingress_bindings.values():
        builder.bind(binding)
    for binding in egress_bindings.values():
        builder.bind(binding)
    return builder.build()


__all__ = ["build_scheduled_address_crossbar_vdut"]
