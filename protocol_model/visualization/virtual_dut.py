"""View-only projection of inspectable VirtualDut realizations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from types import MappingProxyType
from typing import Mapping

from protocol_model.virtual_dut.attachments.address import (
    AddressCompleterAttachment,
    AddressRequesterAttachment,
)
from protocol_model.virtual_dut.attachments.address_operation import (
    AddressAccessOperationAdapter,
    AddressOperationCompleterAttachment,
)
from protocol_model.virtual_dut.attachments.empty import (
    EmptyEndpointAttachment,
    EmptyEndpointMode,
)
from protocol_model.virtual_dut.attachments.notification import (
    NotificationHandlerAttachment,
    NotificationNotifierAttachment,
)
from protocol_model.virtual_dut.attachments.stream import (
    StreamReceiverAttachment,
    StreamTransmitterAttachment,
)
from protocol_model.virtual_dut.backend.address_space import (
    PassiveAddressSpaceBackend,
)
from protocol_model.virtual_dut.backend.interrupt import (
    ExplicitEoiInterruptTargetBackend,
    PriorityInterruptControllerBackend,
)
from protocol_model.virtual_dut.backend.memory_copy import (
    SerializedMemoryCopyBackend,
)
from protocol_model.virtual_dut.backend.queued_address import (
    QueuedAddressResponderBackend,
)
from protocol_model.virtual_dut.backend.sensor_fifo import SensorFifoBackend
from protocol_model.virtual_dut.backend.simple import (
    CaptureBackend,
    FunctionBackend,
    NoOpBackend,
)
from protocol_model.virtual_dut.backend.stepped_emission import (
    SteppedEmissionBackend,
)
from protocol_model.virtual_dut.backend.stream import StreamCaptureBackend
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.fabric.crossbar import (
    ScheduledAddressCrossbarBackend,
)
from protocol_model.virtual_dut.fabric.single_ingress import (
    SingleIngressAddressFabricBackend,
)
from protocol_model.virtual_dut.translation.address_operation_backend import (
    AddressOperationTranslationBridgeBackend,
)

from .policy import DiagramDetail



class DutRealizationView(str, Enum):
    """How much of a VirtualDut implementation this process can inspect."""

    DECLARATION = "declaration"
    OPAQUE = "opaque"
    CONSTRUCTED = "constructed"
    COMPOSITE = "composite"


@dataclass(frozen=True)
class DutComponentView:
    id: str
    kind: str
    label: str
    attributes: Mapping[str, object] = field(default_factory=dict)
    tooltip: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.kind or not self.label:
            raise ValueError("DUT component view requires id, kind, and label")
        object.__setattr__(
            self, "attributes", MappingProxyType(dict(self.attributes))
        )


@dataclass(frozen=True)
class DutFlowView:
    """One visible flow through a DUT realization.

    Solid flows are the forward data/request path used by the layout engine.
    Dashed return flows and dotted control flows remain visible but do not
    constrain component rank.
    """

    source: str
    destination: str
    label: str = ""
    style: str = "solid"

    def __post_init__(self) -> None:
        if not self.source or not self.destination:
            raise ValueError("DUT flow view requires two component ids")
        if self.style not in {"solid", "dashed", "dotted"}:
            raise ValueError("unsupported DUT flow style")


@dataclass(frozen=True)
class DutStructureView:
    dut: str
    realization: DutRealizationView
    components: tuple[DutComponentView, ...]
    flows: tuple[DutFlowView, ...]
    port_components: Mapping[str, str]
    backend_name: str = ""

    def __post_init__(self) -> None:
        components = tuple(self.components)
        flows = tuple(self.flows)
        ids = {component.id for component in components}
        if len(ids) != len(components):
            raise ValueError("DUT structure component ids must be unique")
        if any(
            flow.source not in ids or flow.destination not in ids
            for flow in flows
        ):
            raise ValueError("DUT structure flow references an unknown component")
        ports = dict(self.port_components)
        if any(component not in ids for component in ports.values()):
            raise ValueError("DUT structure port references an unknown component")
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "flows", flows)
        object.__setattr__(self, "port_components", MappingProxyType(ports))


def project_virtual_dut(dut: VirtualDut) -> DutStructureView:
    """Describe visible construction parts without reflecting private state.

    The projection recognizes current constructed backend families explicitly.
    Unknown backends remain one opaque backend node.  Visualization therefore
    does not become a second execution contract and backend code does not need
    to import display types.
    """

    if not isinstance(dut, VirtualDut):
        raise TypeError("VirtualDut projection requires a VirtualDut")

    components: list[DutComponentView] = []
    flows: list[DutFlowView] = []
    ports: dict[str, str] = {}
    attachments: dict[str, str] = {}
    backend = dut.backend

    for index, (name, port) in enumerate(dut.ports.items()):
        component_id = f"port_{index}"
        ports[name] = component_id
        boundary = _binding_side(backend, name)
        port_kind = (
            "transport port"
            if hasattr(port, "transport_family")
            else "interface port"
        )
        components.append(
            DutComponentView(
                component_id,
                "port",
                f"{name}\n{port_kind}",
                _port_attributes(port, boundary=boundary),
            )
        )

    for index, (name, binding) in enumerate(dut.bindings.items()):
        component_id = f"attachment_{index}"
        attachments[name] = component_id
        attachment = binding.attachment
        boundary = _binding_side(backend, name)
        if isinstance(attachment, AddressAccessOperationAdapter):
            codec_id = f"attachment_{index}_codec"
            codec = attachment.attachment
            components.extend(
                (
                    DutComponentView(
                        codec_id,
                        "attachment",
                        _attachment_label(codec),
                        _attachment_attributes(codec, boundary=boundary),
                        type(codec).__name__,
                    ),
                    DutComponentView(
                        component_id,
                        "adapter",
                        "address-access\noperation adapter",
                        {
                            "operation": _operation_signature_text(
                                attachment.operation_signature
                            ),
                        },
                        type(attachment).__name__,
                    ),
                )
            )
            flows.extend(
                (
                    DutFlowView(ports[name], codec_id, "request"),
                    DutFlowView(codec_id, ports[name], "completion", "dashed"),
                    DutFlowView(codec_id, component_id, "AddressAccess"),
                    DutFlowView(
                        component_id,
                        codec_id,
                        "",
                        "dashed",
                    ),
                )
            )
            continue
        components.append(
            DutComponentView(
                component_id,
                "attachment",
                _attachment_label(attachment),
                _attachment_attributes(attachment, boundary=boundary),
                type(attachment).__name__,
            )
        )
        flows.extend(
            _attachment_boundary_flows(
                ports[name], component_id, attachment
            )
        )

    backend_name = "" if backend is None else type(backend).__name__
    if dut.subsystem is not None:
        realization = DutRealizationView.COMPOSITE
        components.append(
            DutComponentView(
                "subsystem",
                "composite",
                "nested SystemProtocol",
            )
        )
        _connect_all(attachments or ports, "subsystem", flows)
    elif backend is None:
        realization = DutRealizationView.DECLARATION
        components.append(
            DutComponentView(
                "opaque",
                "opaque",
                "implementation not modeled",
            )
        )
        _connect_all(attachments or ports, "opaque", flows)
    elif isinstance(backend, SteppedEmissionBackend):
        realization = DutRealizationView.CONSTRUCTED
        inner = backend.inner
        inner_attributes = dict(
            _handler_attributes(inner.address_space)
            if hasattr(inner, "address_space")
            else {}
        )
        inner_attributes["implementation"] = type(inner).__name__
        components.extend(
            (
                DutComponentView(
                    "inner_backend",
                    "behavior",
                    "wrapped backend behavior",
                    inner_attributes,
                ),
                DutComponentView(
                    "emission_fifo",
                    "storage",
                    "deferred output-event FIFO",
                    {"capacity": backend.profile.capacity_events},
                ),
                DutComponentView(
                    "emission_service",
                    "control",
                    "caller-stepped emission",
                    {
                        "rate": "at most 1 event / advance",
                        "batch scheduling": backend.profile.scheduling.value,
                        "ownership": "prepare offer → accept",
                        "wait policy": getattr(
                            backend.profile.wait_policy,
                            "__name__",
                            type(backend.profile.wait_policy).__name__,
                        ),
                    },
                ),
            )
        )
        for attachment in attachments.values():
            flows.append(
                DutFlowView(attachment, "inner_backend", "request / input")
            )
            flows.append(
                DutFlowView(
                    "emission_service",
                    attachment,
                    "one output event",
                    "dashed",
                )
            )
        flows.extend(
            (
                DutFlowView(
                    "inner_backend", "emission_fifo", "completion batch"
                ),
                DutFlowView(
                    "emission_fifo", "emission_service", "ready head"
                ),
            )
        )
    elif isinstance(backend, QueuedAddressResponderBackend):
        realization = DutRealizationView.CONSTRUCTED
        components.extend(
            (
                DutComponentView(
                    "fifo",
                    "storage",
                    "complete-request FIFO",
                    {"capacity": backend.capacity},
                ),
                DutComponentView(
                    "service",
                    "control",
                    "delay / service controller",
                    {"fsm": "DELAYING → READY → service"},
                ),
                DutComponentView(
                    "handler",
                    "behavior",
                    "address access handler",
                    {
                        **_handler_attributes(backend.handler),
                        "implementation": type(backend.handler).__name__,
                    },
                ),
            )
        )
        for attachment in attachments.values():
            flows.append(DutFlowView(attachment, "fifo", "complete access"))
            flows.append(
                DutFlowView("service", attachment, "completion", "dashed")
            )
        flows.extend(
            (
                DutFlowView("fifo", "service", "ready head"),
                DutFlowView("service", "handler", "execute"),
                DutFlowView("handler", "service", "result", "dashed"),
            )
        )
    elif isinstance(backend, PassiveAddressSpaceBackend):
        realization = DutRealizationView.CONSTRUCTED
        components.append(
            DutComponentView(
                "address_space",
                "behavior",
                "AddressSpace",
                _handler_attributes(backend.address_space),
            )
        )
        _connect_all(attachments, "address_space", flows)
    elif isinstance(backend, SerializedMemoryCopyBackend):
        realization = DutRealizationView.CONSTRUCTED
        descriptor = backend.descriptor
        components.extend(
            (
                DutComponentView(
                    "descriptor",
                    "behavior",
                    "fixed copy descriptor",
                    {
                        "source": f"0x{descriptor.source_address:x}",
                        "destination": f"0x{descriptor.destination_address:x}",
                        "length": descriptor.length_bytes,
                        "beat": descriptor.beat_bytes,
                        "strides": (
                            f"{descriptor.source_stride} / "
                            f"{descriptor.destination_stride}"
                        ),
                    },
                ),
                DutComponentView(
                    "copy_fsm",
                    "control",
                    "serialized copy FSM",
                    {
                        "phases": "READ → buffer → WRITE",
                        "outstanding": 1,
                    },
                ),
                DutComponentView(
                    "read_buffer",
                    "storage",
                    "one-beat read buffer",
                    {"capacity": f"{descriptor.beat_bytes} bytes"},
                ),
                DutComponentView(
                    "request_owner",
                    "correlation",
                    "pending request correlation",
                    {"key": "request_id", "active": "0 or 1"},
                ),
            )
        )
        attachment = attachments[backend.binding.name]
        flows.extend(
            (
                DutFlowView(
                    "descriptor", "copy_fsm", "address / length", "dotted"
                ),
                DutFlowView("copy_fsm", "request_owner", "issue read / write"),
                DutFlowView("request_owner", attachment, "address request"),
                DutFlowView(
                    attachment,
                    "request_owner",
                    "completion",
                    "dashed",
                ),
                DutFlowView("request_owner", "read_buffer", "read data"),
                DutFlowView(
                    "read_buffer", "copy_fsm", "next write", "dotted"
                ),
            )
        )
    elif isinstance(backend, SensorFifoBackend):
        realization = DutRealizationView.CONSTRUCTED
        config = backend.config
        policy_name = getattr(
            backend.sample_policy,
            "__name__",
            type(backend.sample_policy).__name__,
        )
        components.extend(
            (
                DutComponentView(
                    "sample_policy",
                    "behavior",
                    "sample value policy",
                    {"callable": policy_name, "input": "immutable counters"},
                    "Caller-supplied deterministic sample policy",
                ),
                DutComponentView(
                    "sensor_service",
                    "control",
                    "explicit sample opportunity",
                    {
                        "trigger": "DutAdvanceAction",
                        "clock": "scenario-owned",
                    },
                ),
                DutComponentView(
                    "sample_fifo",
                    "storage",
                    "sensor sample FIFO",
                    {
                        "capacity": config.capacity,
                        "full": config.full_policy.value,
                        "empty": config.empty_policy.value,
                    },
                ),
                DutComponentView(
                    "data_register",
                    "behavior",
                    "read-to-pop data register",
                    {
                        "address": f"0x{config.data_address:x}",
                        "sample": f"{config.sample_bytes} bytes",
                    },
                ),
            )
        )
        attachment = attachments[backend.binding.name]
        flows.extend(
            (
                DutFlowView("sample_policy", "sensor_service", "next sample"),
                DutFlowView(
                    "sensor_service", "sample_fifo", "enqueue / overrun"
                ),
                DutFlowView(attachment, "data_register", "AddressRead"),
                DutFlowView("sample_fifo", "data_register", "oldest sample"),
                DutFlowView(
                    "data_register", attachment, "AccessResult", "dashed"
                ),
            )
        )
    elif isinstance(backend, PriorityInterruptControllerBackend):
        realization = DutRealizationView.CONSTRUCTED
        components.extend(
            (
                DutComponentView(
                    "interrupt_queue",
                    "storage",
                    "retained edge notifications",
                    {
                        "capacity": backend.capacity,
                        "full": backend.exhaustion_policy.value,
                    },
                ),
                DutComponentView(
                    "priority_select",
                    "control",
                    "priority / arrival-order select",
                    {
                        "priority": "lower value first",
                        "tie": "arrival order",
                        "preemption": "none",
                    },
                ),
                DutComponentView(
                    "active_interrupt",
                    "correlation",
                    "one active target delivery",
                    {"completion": "matching EOI", "active": "0 or 1"},
                ),
            )
        )
        for name in backend.ingress_bindings:
            flows.append(
                DutFlowView(
                    attachments[name],
                    "interrupt_queue",
                    f"retain · {name}",
                )
            )
        target = attachments[backend.target_binding.name]
        flows.extend(
            (
                DutFlowView("interrupt_queue", "priority_select", "pending"),
                DutFlowView(
                    "priority_select", "active_interrupt", "activate"
                ),
                DutFlowView("active_interrupt", target, "notify target"),
                DutFlowView(target, "active_interrupt", "EOI", "dashed"),
            )
        )
    elif isinstance(backend, ExplicitEoiInterruptTargetBackend):
        realization = DutRealizationView.CONSTRUCTED
        components.extend(
            (
                DutComponentView(
                    "target_active",
                    "storage",
                    "single active interrupt",
                    {"capacity": 1},
                ),
                DutComponentView(
                    "eoi_control",
                    "control",
                    "explicit EOI service",
                    {"trigger": "DutAdvanceAction"},
                ),
            )
        )
        attachment = attachments[backend.binding.name]
        flows.extend(
            (
                DutFlowView(attachment, "target_active", "notification"),
                DutFlowView(
                    "target_active", "eoi_control", "handled edge"
                ),
                DutFlowView(
                    "eoi_control", attachment, "completion", "dashed"
                ),
            )
        )
    elif isinstance(backend, AddressOperationTranslationBridgeBackend):
        realization = DutRealizationView.CONSTRUCTED
        stages = tuple(stage.name for stage in backend.executor.plan.stages)
        components.extend(
            (
                DutComponentView(
                    "translation",
                    "transform",
                    "typed translation",
                    {
                        "pipeline": _compact_stage_pipeline(stages),
                    },
                    "TranslationPlan stages: "
                    + (" → ".join(stages) or "identity"),
                ),
                DutComponentView(
                    "scheduler",
                    "control",
                    "serial scheduler",
                    {
                        "parent capacity": backend.executor.profile.parent_capacity,
                        "child issue": "one at a time",
                    },
                ),
                DutComponentView(
                    "owner",
                    "correlation",
                    "child owner table",
                    {"completion": "child → parent fold"},
                ),
            )
        )
        ingress = attachments[backend.ingress_port]
        egress = attachments[backend.egress_port]
        flows.extend(
            (
                DutFlowView(ingress, "translation", ""),
                DutFlowView("translation", "scheduler", "children"),
                DutFlowView("scheduler", "owner", ""),
                DutFlowView("owner", egress, "request"),
                DutFlowView(egress, "owner", "completion", "dashed"),
                DutFlowView("owner", "translation", "fold", "dashed"),
                DutFlowView("translation", ingress, "", "dashed"),
            )
        )
    elif isinstance(backend, SingleIngressAddressFabricBackend):
        realization = DutRealizationView.CONSTRUCTED
        route_text = ", ".join(
            f"0x{route.base_address:x}+0x{route.size_bytes:x}→{route.egress_port}"
            for route in backend.routes
        )
        components.extend(
            (
                DutComponentView(
                    "route",
                    "routing",
                    "address decoder / remap",
                    {"routes": route_text},
                ),
                DutComponentView(
                    "owner",
                    "correlation",
                    "pending owner / response mux",
                    {"active requests": 1},
                ),
            )
        )
        ingress = attachments[backend.ingress_port]
        flows.append(DutFlowView(ingress, "route", "decoded access"))
        flows.append(DutFlowView("route", "owner", "selected egress"))
        for name in backend.egress_bindings:
            egress = attachments[name]
            flows.append(DutFlowView("owner", egress, f"request · {name}"))
            flows.append(DutFlowView(egress, "owner", "completion", "dashed"))
        flows.append(DutFlowView("owner", ingress, "return", "dashed"))
    elif isinstance(backend, ScheduledAddressCrossbarBackend):
        realization = DutRealizationView.CONSTRUCTED
        route_text = ", ".join(
            f"0x{route.base_address:x}+0x{route.size_bytes:x}"
            f"→{route.egress_port}"
            for route in backend.routes
        )
        components.extend(
            (
                DutComponentView(
                    "route",
                    "routing",
                    "shared address decoder / remap",
                    {
                        "routes": route_text,
                        "miss": "ordered decode-error completion",
                    },
                    "A route is resolved at admission and retained with the "
                    "queued request.",
                ),
                DutComponentView(
                    "owner",
                    "correlation",
                    "active owner / return table",
                    {
                        "key": "request_id",
                        "mapping": "ingress ↔ egress",
                        "max active": min(
                            len(backend.ingress_ports), len(backend.egress_ports)
                        ),
                    },
                ),
            )
        )

        ingress_fifos: dict[str, str] = {}
        for index, name in enumerate(backend.ingress_ports):
            fifo_id = f"ingress_fifo_{index}"
            ingress_fifos[name] = fifo_id
            components.append(
                DutComponentView(
                    fifo_id,
                    "storage",
                    f"{name}\ncomplete-request FIFO",
                    {
                        "ingress": name,
                        "capacity": backend.ingress_queue_capacity,
                        "ordering": "FIFO",
                    },
                )
            )

        egress_arbiters: dict[str, str] = {}
        ingress_order = ", ".join(backend.ingress_ports)
        for index, name in enumerate(backend.egress_ports):
            arbiter_id = f"egress_arbiter_{index}"
            egress_arbiters[name] = arbiter_id
            components.append(
                DutComponentView(
                    arbiter_id,
                    "control",
                    f"{name}\nround-robin arbiter / cursor",
                    {
                        "egress": name,
                        "policy": "round-robin",
                        "ingress order": ingress_order,
                        "grant": "at most one / advance",
                    },
                )
            )

        for name, fifo_id in ingress_fifos.items():
            ingress = attachments[name]
            flows.extend(
                (
                    DutFlowView(ingress, "route", "complete access"),
                    DutFlowView("route", fifo_id, "routed / remapped"),
                    DutFlowView("owner", ingress, f"return · {name}", "dashed"),
                )
            )
        for name, arbiter_id in egress_arbiters.items():
            egress = attachments[name]
            flows.extend(
                (
                    *(
                        DutFlowView(
                            fifo_id,
                            arbiter_id,
                            f"eligible head · {name}",
                        )
                        for fifo_id in ingress_fifos.values()
                    ),
                    DutFlowView(arbiter_id, egress, f"request · {name}"),
                    DutFlowView(
                        arbiter_id,
                        "owner",
                        f"record owner · {name}",
                        "dotted",
                    ),
                    DutFlowView(egress, "owner", "completion", "dashed"),
                    DutFlowView(
                        "owner",
                        arbiter_id,
                        "active ownership",
                        "dotted",
                    ),
                )
            )
    elif isinstance(backend, StreamCaptureBackend):
        realization = DutRealizationView.CONSTRUCTED
        components.append(
            DutComponentView(
                "capture",
                "storage",
                "ordered StreamTransfer capture",
            )
        )
        for attachment in attachments.values():
            flows.append(DutFlowView(attachment, "capture", "transfer"))
    elif isinstance(backend, (NoOpBackend, CaptureBackend, FunctionBackend)):
        realization = DutRealizationView.CONSTRUCTED
        if isinstance(backend, NoOpBackend):
            backend_label = "no autonomous behavior"
            backend_attributes: Mapping[str, object] = {}
            backend_tooltip = (
                "NoOpBackend: this DUT emits no events by itself; an external "
                "scenario controller remains outside the DUT boundary"
            )
        elif isinstance(backend, CaptureBackend):
            backend_label = "received-event capture"
            backend_attributes = {"emission": "none"}
            backend_tooltip = (
                "CaptureBackend: records delivered PortInput events and emits "
                "no protocol events"
            )
        else:
            backend_label = "event transform"
            backend_attributes = {"mapping": "input → zero or more outputs"}
            backend_tooltip = "FunctionBackend"
        components.append(
            DutComponentView(
                "backend",
                "behavior",
                backend_label,
                backend_attributes,
                tooltip=backend_tooltip,
            )
        )
        if isinstance(backend, CaptureBackend):
            for source in (attachments or ports).values():
                flows.append(DutFlowView(source, "backend", "received event"))
        elif isinstance(backend, NoOpBackend):
            if not attachments:
                for source in ports.values():
                    flows.append(DutFlowView(source, "backend", "consume"))
            else:
                for name, attachment_id in attachments.items():
                    attachment = dut.bindings[name].attachment
                    if (
                        isinstance(attachment, EmptyEndpointAttachment)
                        and attachment.mode is EmptyEndpointMode.IDLE_SOURCE
                    ):
                        flows.append(
                            DutFlowView(
                                "backend",
                                attachment_id,
                                "no autonomous emission",
                                "dotted",
                            )
                        )
                    else:
                        flows.append(
                            DutFlowView(attachment_id, "backend", "consume")
                        )
        else:
            _connect_all(attachments or ports, "backend", flows)
    else:
        # A visible attachment does not make an arbitrary backend inspectable.
        # Keep the known protocol boundary outside a deliberately opaque
        # implementation node instead of classifying the whole realization as
        # constructed.
        realization = DutRealizationView.OPAQUE
        components.append(
            DutComponentView(
                "backend",
                "opaque",
                "opaque backend",
                {
                    "detail": "backend internals have no registered projector",
                    "implementation": backend_name,
                },
            )
        )
        _connect_all(attachments or ports, "backend", flows)

    return DutStructureView(
        dut.name,
        realization,
        tuple(components),
        tuple(flows),
        ports,
        backend_name,
    )


def virtual_dut_structure_dot(
    dut: VirtualDut | DutStructureView,
    *,
    title: str | None = None,
    detail: DiagramDetail = DiagramDetail.STANDARD,
) -> str:
    """Render one VirtualDut boundary with its visible construction parts."""

    detail = DiagramDetail(detail)
    structure = (
        dut if isinstance(dut, DutStructureView) else project_virtual_dut(dut)
    )
    lines = [
        "digraph virtual_dut_structure {",
        "  rankdir=LR;",
        f"  label={_quoted(title or _structure_title(structure, detail))};",
        '  labelloc="t";',
        '  graph [bgcolor="white", pad=0.25, nodesep=0.28, '
        'ranksep=0.62, splines=polyline, newrank=true];',
        '  node [fontname="sans-serif", fontsize=10, shape=box, '
        'style="rounded,filled", fillcolor="#ffffff"];',
        '  edge [fontname="sans-serif", fontsize=9, color="#52606d"];',
        "  subgraph cluster_virtual_dut {",
        f"    label={_quoted(_boundary_title(structure, detail))};",
        '    color="#64748b";',
        '    penwidth=1.4;',
        '    style="rounded";',
    ]
    lines.extend(
        _structure_dot_lines(
            structure,
            prefix="component",
            indent="    ",
            detail=detail,
        )
    )
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _connect_all(
    sources: Mapping[str, str],
    destination: str,
    flows: list[DutFlowView],
) -> None:
    for source in sources.values():
        flows.append(DutFlowView(source, destination, "request / input"))
        flows.append(
            DutFlowView(destination, source, "response / output", "dashed")
        )


def _handler_attributes(handler: object) -> Mapping[str, object]:
    regions = getattr(handler, "regions", None)
    if regions is None:
        return {}
    return {
        "regions": ", ".join(
            f"{region.name}@0x{region.base_address:x}+0x{region.size_bytes:x}"
            for region in regions
        )
    }


def _port_attributes(
    port: object,
    *,
    boundary: str = "",
) -> Mapping[str, object]:
    protocol = getattr(port, "protocol", None)
    if protocol is not None:
        role = getattr(port, "role")
        incoming = tuple(
            channel.schema.name
            for channel in protocol.event_kinds.values()
            if channel.destination_role == role
        )
        outgoing = tuple(
            channel.schema.name
            for channel in protocol.event_kinds.values()
            if channel.source_role == role
        )
        attributes: dict[str, object] = {
            "interface": f"{protocol.name} · {role}",
            "in": _event_kind_text(incoming),
            "out": _event_kind_text(outgoing),
        }
    else:
        family = getattr(port, "transport_family")
        direction = getattr(port, "direction")
        attributes = {
            "transport": f"{family} · {direction.value}",
            "in": "flit" if direction.value == "receive" else "—",
            "out": "flit" if direction.value == "transmit" else "—",
        }
    if boundary:
        attributes["side"] = boundary
    clock_domain = getattr(port, "clock_domain", None)
    reset_domain = getattr(port, "reset_domain", None)
    if clock_domain is not None:
        attributes["clock"] = clock_domain
    if reset_domain is not None:
        attributes["reset"] = reset_domain
    return attributes


def _attachment_attributes(
    attachment: object,
    *,
    boundary: str = "",
) -> Mapping[str, object]:
    protocol = getattr(attachment, "protocol", None)
    role = getattr(attachment, "role", "")
    attributes: dict[str, object] = {}
    if boundary:
        attributes["side"] = boundary
    if protocol is not None:
        attributes["binding"] = f"{protocol.name} · {role}"
    attributes.update(
        {
            "in": _event_kind_text(
                getattr(attachment, "incoming_event_kinds", ())
            ),
            "out": _event_kind_text(
                getattr(attachment, "outgoing_event_kinds", ())
            ),
        }
    )
    operation = _attachment_operation_text(attachment)
    if operation:
        attributes["operation"] = operation
    if isinstance(attachment, EmptyEndpointAttachment):
        attributes["mode"] = attachment.mode.value
    attributes["implementation"] = type(attachment).__name__
    return attributes


def _event_kind_text(kinds: object) -> str:
    names = tuple(sorted(str(item) for item in kinds))
    if not names:
        return "—"
    visible = names[:6]
    suffix = "" if len(names) <= 6 else f", +{len(names) - 6}"
    one_line = ", ".join(visible) + suffix
    if len(one_line) <= 24:
        return one_line
    return ",\n".join(visible) + suffix


def _attachment_label(attachment: object) -> str:
    if isinstance(attachment, AddressRequesterAttachment):
        return "address requester\nattachment"
    if isinstance(
        attachment,
        (AddressCompleterAttachment, AddressOperationCompleterAttachment),
    ):
        return "address completer\nattachment"
    if isinstance(attachment, StreamTransmitterAttachment):
        return "stream transmitter\nattachment"
    if isinstance(attachment, StreamReceiverAttachment):
        return "stream receiver\nattachment"
    if isinstance(attachment, NotificationNotifierAttachment):
        return "notification source\nattachment"
    if isinstance(attachment, NotificationHandlerAttachment):
        return "notification handler\nattachment"
    if isinstance(attachment, EmptyEndpointAttachment):
        return "empty endpoint\nattachment"
    return "interface\nattachment"


def _attachment_operation_text(attachment: object) -> str:
    signature = getattr(attachment, "operation_signature", None)
    if signature is not None:
        return _operation_signature_text(signature)
    if isinstance(
        attachment, (AddressCompleterAttachment, AddressRequesterAttachment)
    ):
        return "AddressRead | AddressWrite\n→ AccessResult"
    if isinstance(
        attachment, (StreamReceiverAttachment, StreamTransmitterAttachment)
    ):
        return "StreamTransfer"
    if isinstance(
        attachment,
        (NotificationHandlerAttachment, NotificationNotifierAttachment),
    ):
        return "Notification → Completion"
    if isinstance(attachment, EmptyEndpointAttachment):
        if attachment.mode is EmptyEndpointMode.IDLE_SOURCE:
            return "none (idle)"
        return "consume event only"
    if callable(getattr(attachment, "decode_request", None)) and callable(
        getattr(attachment, "encode_completion", None)
    ):
        return "protocol request → completion"
    return ""


def _operation_signature_text(signature: object) -> str:
    requests = " | ".join(
        item.__name__ for item in signature.request_types
    ) or "—"
    completions = " | ".join(
        item.__name__ for item in signature.completion_types
    ) or "—"
    return f"{requests}\n→ {completions}"


def _binding_side(backend: object | None, name: str) -> str:
    if backend is None:
        return ""
    if getattr(backend, "ingress_port", None) == name:
        return "ingress"
    if getattr(backend, "egress_port", None) == name:
        return "egress"
    ingress_bindings = getattr(backend, "ingress_bindings", {})
    if name in ingress_bindings:
        return "ingress"
    egress_bindings = getattr(backend, "egress_bindings", {})
    if name in egress_bindings:
        return "egress"
    target_binding = getattr(backend, "target_binding", None)
    if target_binding is not None and target_binding.name == name:
        return "target"
    return ""


def _attachment_boundary_flows(
    port: str,
    attachment_id: str,
    attachment: object,
) -> tuple[DutFlowView, ...]:
    if isinstance(attachment, AddressRequesterAttachment):
        return (
            DutFlowView(attachment_id, port, "request"),
            DutFlowView(port, attachment_id, "completion", "dashed"),
        )
    if isinstance(
        attachment,
        (AddressCompleterAttachment, AddressOperationCompleterAttachment),
    ):
        return (
            DutFlowView(port, attachment_id, "request"),
            DutFlowView(attachment_id, port, "completion", "dashed"),
        )
    if isinstance(attachment, StreamTransmitterAttachment):
        return (DutFlowView(attachment_id, port, "transfer"),)
    if isinstance(attachment, StreamReceiverAttachment):
        return (DutFlowView(port, attachment_id, "transfer"),)
    if isinstance(attachment, NotificationNotifierAttachment):
        return (
            DutFlowView(attachment_id, port, "notification"),
            DutFlowView(port, attachment_id, "completion", "dashed"),
        )
    if isinstance(attachment, NotificationHandlerAttachment):
        return (
            DutFlowView(port, attachment_id, "notification"),
            DutFlowView(attachment_id, port, "completion", "dashed"),
        )
    if isinstance(attachment, EmptyEndpointAttachment):
        if attachment.mode is EmptyEndpointMode.IDLE_SOURCE:
            return (DutFlowView(attachment_id, port, "declared output"),)
        return (DutFlowView(port, attachment_id, "accepted input"),)
    return (
        DutFlowView(port, attachment_id, "events in"),
        DutFlowView(attachment_id, port, "events out", "dashed"),
    )


def _compact_stage_pipeline(stages: tuple[str, ...]) -> str:
    if not stages:
        return "identity"
    compact = tuple(_compact_stage_name(stage) for stage in stages)
    return "\n→ ".join(compact)


def _compact_stage_name(name: str) -> str:
    if name.startswith("decode_amba_") and name.endswith("_protection"):
        return "decode protection"
    if name.startswith("encode_amba_") and name.endswith("_protection"):
        return "encode protection"
    if name.startswith("shape_for_"):
        return "target shape"
    if name == "address_route":
        return "address route"
    return name.replace("_", " ")


def _structure_title(
    structure: DutStructureView,
    detail: DiagramDetail,
) -> str:
    if detail is DiagramDetail.OVERVIEW:
        return f"{structure.dut} · VirtualDut"
    if detail is DiagramDetail.STANDARD:
        return (
            f"{structure.dut} · VirtualDut · {structure.realization.value}"
        )
    backend_detail = structure.backend_name or "no executable backend"
    return (
        f"{structure.dut} · VirtualDut · {structure.realization.value}\n"
        f"visible realization: bindings + {backend_detail}"
    )


def _boundary_title(
    structure: DutStructureView,
    detail: DiagramDetail,
) -> str:
    if detail is DiagramDetail.OVERVIEW:
        return "module boundary"
    if detail is DiagramDetail.STANDARD:
        return "VirtualDut boundary"
    return structure.dut + " · VirtualDut boundary"


_OVERVIEW_ATTRIBUTE_KEYS = frozenset(
    (
        "interface",
        "transport",
        "binding",
        "capacity",
        "parent capacity",
        "max active",
    )
)

_STANDARD_HIDDEN_ATTRIBUTE_KEYS = frozenset(
    (
        "implementation",
        "in",
        "out",
        "side",
        "ingress",
        "egress",
        "ingress order",
        "wait policy",
        "batch scheduling",
        "ownership",
        "callable",
        "input",
        "operation",
    )
)


def _component_label(
    component: DutComponentView,
    detail: DiagramDetail,
) -> str:
    if detail is DiagramDetail.OVERVIEW:
        attributes = (
            (key, value)
            for key, value in component.attributes.items()
            if key in _OVERVIEW_ATTRIBUTE_KEYS
        )
    elif detail is DiagramDetail.STANDARD:
        attributes = (
            (key, value)
            for key, value in component.attributes.items()
            if key not in _STANDARD_HIDDEN_ATTRIBUTE_KEYS
        )
    else:
        attributes = component.attributes.items()
    details = [
        f"{key}: {value}"
        for key, value in attributes
        if value not in {None, ""}
    ]
    return "\n".join((component.label, *details))


def _structure_dot_lines(
    structure: DutStructureView,
    *,
    prefix: str,
    indent: str = "  ",
    detail: DiagramDetail = DiagramDetail.DIAGNOSTIC,
) -> list[str]:
    detail = DiagramDetail(detail)
    ids = {
        component.id: f"{prefix}_{index}"
        for index, component in enumerate(structure.components)
    }
    colors = {
        "port": ("#dbeafe", "#2563eb"),
        "attachment": ("#e0f2fe", "#0284c7"),
        "adapter": ("#cffafe", "#0891b2"),
        "storage": ("#fef3c7", "#d97706"),
        "control": ("#ede9fe", "#7c3aed"),
        "behavior": ("#dcfce7", "#16a34a"),
        "transform": ("#fae8ff", "#c026d3"),
        "correlation": ("#ffedd5", "#ea580c"),
        "routing": ("#fce7f3", "#db2777"),
        "opaque": ("#f1f5f9", "#64748b"),
        "composite": ("#ecfccb", "#65a30d"),
    }
    lines: list[str] = []
    for component in structure.components:
        fill, color = colors.get(component.kind, ("#ffffff", "#64748b"))
        shape = "box"
        penwidth = "1.5" if component.kind == "port" else "1.0"
        if detail is DiagramDetail.DIAGNOSTIC:
            tooltip = component.tooltip or _component_label(
                component, DiagramDetail.DIAGNOSTIC
            )
        else:
            tooltip = _component_label(component, detail)
        lines.append(
            f"{indent}{ids[component.id]} [shape={shape}, "
            f"fillcolor={_quoted(fill)}, color={_quoted(color)}, "
            f"penwidth={penwidth}, "
            f"label={_quoted(_component_label(component, detail))}, "
            f"tooltip={_quoted(tooltip)}];"
        )
    ingress_ports = tuple(
        ids[component.id]
        for component in structure.components
        if component.kind == "port"
        and component.attributes.get("side") == "ingress"
    )
    egress_ports = tuple(
        ids[component.id]
        for component in structure.components
        if component.kind == "port"
        and component.attributes.get("side") == "egress"
    )
    if ingress_ports and egress_ports:
        lines.append(
            f"{indent}{{ rank=source; {'; '.join(ingress_ports)}; }}"
        )
        lines.append(
            f"{indent}{{ rank=sink; {'; '.join(egress_ports)}; }}"
        )
        for side in ("ingress", "egress"):
            bank = tuple(
                ids[component.id]
                for component in structure.components
                if component.kind in {"attachment", "adapter"}
                and component.attributes.get("side") == side
            )
            if len(bank) > 1:
                lines.append(
                    f"{indent}{{ rank=same; {'; '.join(bank)}; }}"
                )
        ingress_bank = tuple(
            ids[component.id]
            for component in structure.components
            if component.kind in {"attachment", "adapter"}
            and component.attributes.get("side") == "ingress"
        )
        egress_bank = tuple(
            ids[component.id]
            for component in structure.components
            if component.kind in {"attachment", "adapter"}
            and component.attributes.get("side") == "egress"
        )
        solid_components = {
            endpoint
            for flow in structure.flows
            if flow.style == "solid"
            for endpoint in (flow.source, flow.destination)
        }
        floating_correlations = tuple(
            ids[component.id]
            for component in structure.components
            if component.kind == "correlation"
            and component.id not in solid_components
        )
        if ingress_bank and egress_bank:
            for correlation in floating_correlations:
                lines.append(
                    f"{indent}{ingress_bank[0]} -> {correlation} "
                    "[style=invis, constraint=true, weight=1];"
                )
                lines.append(
                    f"{indent}{correlation} -> {egress_bank[0]} "
                    "[style=invis, constraint=true, weight=1];"
                )
    for flow in structure.flows:
        # Return/control relations are preserved in the projected ViewIR, but
        # drawing every one of them makes the default construction view read
        # like a debugger dump.  Diagnostic mode remains the lossless view.
        if (
            flow.style != "solid"
            and detail is not DiagramDetail.DIAGNOSTIC
        ):
            continue
        if flow.style == "solid":
            layout = 'constraint=true, weight=4, color="#475569"'
        elif flow.style == "dashed":
            layout = (
                'constraint=false, color="#94a3b8", '
                'fontcolor="#64748b"'
            )
        else:
            layout = (
                'constraint=false, color="#7c3aed", '
                'fontcolor="#7c3aed"'
            )
        flow_label = flow.label
        if detail is DiagramDetail.OVERVIEW:
            flow_label = ""
        lines.append(
            f"{indent}{ids[flow.source]} -> {ids[flow.destination]} "
            f"[style={flow.style}, {layout}, "
            f"label={_quoted(flow_label)}];"
        )
    return lines


def _quoted(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


__all__ = [
    "DutComponentView",
    "DutFlowView",
    "DutRealizationView",
    "DutStructureView",
    "project_virtual_dut",
    "virtual_dut_structure_dot",
]
