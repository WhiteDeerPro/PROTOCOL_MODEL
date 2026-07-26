#!/usr/bin/env python3
"""Publish an AXI4-Lite one-manager, three-subordinate fabric witness."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory


if sys.version_info < (3, 10):
    raise SystemExit("this demo requires Python 3.10 or newer")


DEMO_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = DEMO_DIRECTORY.parents[3]
SHOWCASE_ROOT = REPOSITORY_ROOT / "showcase"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from protocol_model import __version__  # noqa: E402
from protocol_model.artifacts import (  # noqa: E402
    RunArtifactStore,
    protocol_record_from_interface,
    protocol_record_from_system,
)
from protocol_model.integrations.recipes.amba.endpoints import (  # noqa: E402
    build_axi4_lite_address_space_vdut,
)
from protocol_model.integrations.recipes.amba.fabrics import (  # noqa: E402
    build_axi4_lite_address_fabric_vdut,
)
from protocol_model.integrations.attachments.amba.axi.axi4_lite.common import (  # noqa: E402
    Axi4LiteCompleterState,
)
from protocol_model.protocols.amba.axi.axi4_lite import (  # noqa: E402
    build_axi4_lite_interface,
)
from protocol_model.semantics import CanonicalEvent  # noqa: E402
from protocol_model.system import (  # noqa: E402
    AddressClaim,
    AddressRouterContract,
    AddressWindow,
    SystemAction,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.address import (  # noqa: E402
    AddressSpace,
    MemoryRegion,
    RegisterPermission,
    RegisterRegion,
    RegisterSpec,
)
from protocol_model.virtual_dut.backend import (  # noqa: E402
    CaptureBackend,
    CaptureState,
)
from protocol_model.virtual_dut.boundary import (  # noqa: E402
    InterfacePort,
    VirtualDut,
)
from protocol_model.virtual_dut.fabric import (  # noqa: E402
    AddressRoute,
    SingleIngressAddressFabricState,
)
from protocol_model.visualization import (  # noqa: E402
    VisualizationPublisher,
    system_bus_strip_dot,
    system_topology_dot,
    system_trace_dot,
    virtual_dut_structure_dot,
)


DEMO_NAME = "axi4-lite-single-manager-fabric"
SYSTEM_NAME = "axi4_lite_single_manager_fabric"
FABRIC_NAME = "fabric"

CONTROL_BASE = 0x1000
STATUS_BASE = 0x2000
MEMORY_BASE = 0x4000
UNMAPPED_ADDRESS = 0x3000
REGISTER_BYTES = 4
MEMORY_BYTES = 0x100

CONTROL_VALUE = 0x11223344
STATUS_VALUE = 0xA5A50001
MEMORY_VALUE = 0xDEADBEEF


def _manager(protocol) -> VirtualDut:
    return VirtualDut(
        "manager",
        {"axi": InterfacePort("axi", protocol, "manager")},
        backend=CaptureBackend(),
        description="scenario-driven AXI4-Lite manager boundary",
    )


def _register_endpoint(
    name: str,
    protocol,
    *,
    reset: int,
    permission: RegisterPermission,
) -> VirtualDut:
    return build_axi4_lite_address_space_vdut(
        name,
        protocol,
        AddressSpace(
            (
                RegisterRegion(
                    f"{name}_registers",
                    (
                        RegisterSpec(
                            "value",
                            0,
                            reset=reset,
                            permission=permission,
                        ),
                    ),
                ),
            )
        ),
        port_name="axi",
    )


def _memory_endpoint(protocol) -> VirtualDut:
    return build_axi4_lite_address_space_vdut(
        "memory",
        protocol,
        AddressSpace((MemoryRegion("ram", MEMORY_BYTES),)),
        port_name="axi",
    )


def _build_system():
    protocol = build_axi4_lite_interface()
    routes = (
        AddressRoute(
            "control",
            CONTROL_BASE,
            REGISTER_BYTES,
            "control",
            output_base_address=0,
        ),
        AddressRoute(
            "status",
            STATUS_BASE,
            REGISTER_BYTES,
            "status",
            output_base_address=0,
        ),
        AddressRoute(
            "memory",
            MEMORY_BASE,
            MEMORY_BYTES,
            "memory",
            output_base_address=0,
        ),
    )
    router = AddressRouterContract(
        "peripheral_address_map",
        FABRIC_NAME,
        ("upstream",),
        ("control", "status", "memory"),
        routes,
    )

    builder = SystemProtocolBuilder(SYSTEM_NAME)
    for dut in (
        _manager(protocol),
        _register_endpoint(
            "control",
            protocol,
            reset=0,
            permission=RegisterPermission.READ_WRITE,
        ),
        _register_endpoint(
            "status",
            protocol,
            reset=STATUS_VALUE,
            permission=RegisterPermission.READ_ONLY,
        ),
        _memory_endpoint(protocol),
    ):
        builder.add_dut(dut)

    # One AddressRouterContract is the authority for both the constructed
    # module boundary and SystemProtocol address resolution.  Construction
    # rejects a fabric whose projected ports or routes disagree with it.
    builder.construct_address_router(
        router,
        lambda contract: build_axi4_lite_address_fabric_vdut(
            contract.router,
            protocol,
            contract.routes,
            ingress_port=contract.ingress_ports[0],
        ),
    )
    builder.connect(
        "manager_bus",
        protocol,
        {
            "manager": VirtualDutPortRef("manager", "axi"),
            "subordinate": VirtualDutPortRef(FABRIC_NAME, "upstream"),
        },
    )
    for target in ("control", "status", "memory"):
        builder.connect(
            f"{target}_bus",
            protocol,
            {
                "manager": VirtualDutPortRef(FABRIC_NAME, target),
                "subordinate": VirtualDutPortRef(target, "axi"),
            },
        )
    for target, size in (
        ("control", REGISTER_BYTES),
        ("status", REGISTER_BYTES),
        ("memory", MEMORY_BYTES),
    ):
        builder.add_address_claim(
            AddressClaim(
                f"{target}_local",
                VirtualDutPortRef(target, "axi"),
                AddressWindow(0, size),
            )
        )
    return builder.build(), protocol


def _event(kind: str, payload: dict[str, object]) -> SystemAction:
    return SystemAction(
        VirtualDutPortRef("manager", "axi"),
        CanonicalEvent(kind, None, payload),
    )


def _write_data(data: int) -> SystemAction:
    return _event("W", {"data": data, "strb": 0b1111})


def _write_address(address: int) -> SystemAction:
    return _event("AW", {"addr": address, "prot": 0})


def _read(address: int) -> SystemAction:
    return _event("AR", {"addr": address, "prot": 0})


def _fabric_snapshot(state) -> dict[str, object]:
    fabric = state.dut_states[FABRIC_NAME]
    if not isinstance(fabric, SingleIngressAddressFabricState):
        raise TypeError("demo expected SingleIngressAddressFabricState")
    ingress = fabric.ingress_state
    if not isinstance(ingress, Axi4LiteCompleterState):
        raise TypeError("demo expected Axi4LiteCompleterState")
    return {
        "pending_aw": len(ingress.pending_aw),
        "pending_w": len(ingress.pending_w),
        "active_owner_count": len(fabric.pending),
        "active_owners": [
            {
                "request_id": request_id,
                "egress": owner.egress_port,
            }
            for request_id, owner in sorted(fabric.pending.items())
        ],
        "next_request_id": fabric.next_request_id,
    }


def _captured(state) -> tuple[CanonicalEvent, ...]:
    manager = state.dut_states["manager"]
    if not isinstance(manager, CaptureState):
        raise TypeError("demo expected CaptureState")
    return tuple(item.event for item in manager.received)


def _emission_record(item) -> dict[str, object]:
    return {
        "index": item.index,
        "connection": item.connection,
        "source": item.source.qualified_name,
        "destination": item.destination.qualified_name,
        "kind": item.event.kind,
        "payload": dict(item.event.payload),
    }


def _record(label: str, action: str, transition) -> dict[str, object]:
    responses = [
        item
        for item in transition.emissions
        if item.destination == VirtualDutPortRef("manager", "axi")
    ]
    return {
        "label": label,
        "action": action,
        "fault": (
            None
            if transition.fault is None
            else {
                "rule": transition.fault.rule,
                "reason": transition.fault.reason,
            }
        ),
        "fabric": _fabric_snapshot(transition.state),
        "manager_response": (
            "—"
            if not responses
            else " + ".join(_event_summary(item.event) for item in responses)
        ),
        "emissions": [
            _emission_record(item) for item in transition.emissions
        ],
    }


def _execute(system):
    session = system.open_session()
    state = session.initial_state()
    records: list[dict[str, object]] = []
    actions = (
        (
            "S0 · hold control write data",
            "W control=0x11223344",
            _write_data(CONTROL_VALUE),
        ),
        (
            "S1 · route joined control write",
            "AW 0x1000",
            _write_address(CONTROL_BASE),
        ),
        (
            "S2 · read control",
            "AR 0x1000",
            _read(CONTROL_BASE),
        ),
        (
            "S3 · read read-only status",
            "AR 0x2000",
            _read(STATUS_BASE),
        ),
        (
            "S4 · hold memory write address",
            "AW 0x4000",
            _write_address(MEMORY_BASE),
        ),
        (
            "S5 · route joined memory write",
            "W memory=0xdeadbeef",
            _write_data(MEMORY_VALUE),
        ),
        (
            "S6 · read memory",
            "AR 0x4000",
            _read(MEMORY_BASE),
        ),
        (
            "S7 · read unmapped address",
            "AR 0x3000",
            _read(UNMAPPED_ADDRESS),
        ),
    )
    for label, action_name, action in actions:
        transition = session.step(state, action)
        records.append(_record(label, action_name, transition))
        if transition.fault is not None:
            raise RuntimeError(
                f"fabric witness failed at {label}: "
                f"{transition.fault.rule}: {transition.fault.reason}"
            )
        state = transition.state

    responses = _captured(state)
    expected = (
        ("B", "OKAY", None),
        ("R", "OKAY", CONTROL_VALUE),
        ("R", "OKAY", STATUS_VALUE),
        ("B", "OKAY", None),
        ("R", "OKAY", MEMORY_VALUE),
        ("R", "DECERR", 0),
    )
    observed = tuple(
        (
            event.kind,
            str(event.payload["resp"]),
            None if event.kind == "B" else int(event.payload["data"]),
        )
        for event in responses
    )
    if observed != expected:
        raise RuntimeError(
            f"manager response mismatch: expected {expected!r}, got {observed!r}"
        )
    if not session.is_quiescent(state):
        raise RuntimeError("fabric witness did not return to quiescence")
    return session, state, records, responses


def _event_summary(event: CanonicalEvent) -> str:
    payload = event.payload
    if event.kind in {"AW", "AR"}:
        return f"{event.kind}@0x{int(payload['addr']):04x}"
    if event.kind == "W":
        return f"W=0x{int(payload['data']):08x}"
    if event.kind == "B":
        return f"B {payload['resp']}"
    if event.kind == "R":
        return f"R {payload['resp']} 0x{int(payload['data']):08x}"
    return event.kind


def _categorical_lane(
    name: str,
    values: list[object],
) -> dict[str, object]:
    return {
        "name": name,
        "wave": "=" * len(values),
        "data": [str(value) for value in values],
    }


def _connection_lane(
    records: list[dict[str, object]],
    name: str,
    connection: str,
) -> dict[str, object]:
    values: list[str] = []
    for record in records:
        events = [
            item
            for item in record["emissions"]
            if item["connection"] == connection
        ]
        values.append(
            "—"
            if not events
            else " · ".join(
                f"e{item['index']} "
                + _event_summary(
                    CanonicalEvent(
                        str(item["kind"]),
                        None,
                        dict(item["payload"]),
                    )
                )
                for item in events
            )
        )
    return _categorical_lane(name, values)


def _wavejson(records: list[dict[str, object]]) -> dict[str, object]:
    fabrics = [record["fabric"] for record in records]
    return {
        "signal": [
            _categorical_lane(
                "MODEL STEP · not clock",
                [f"S{index}" for index in range(len(records))],
            ),
            [
                "scenario",
                _categorical_lane(
                    "injected event",
                    [record["action"] for record in records],
                ),
                _categorical_lane(
                    "manager response",
                    [record["manager_response"] for record in records],
                ),
            ],
            [
                "accepted interface events",
                _connection_lane(
                    records, "manager ↔ fabric", "manager_bus"
                ),
                _connection_lane(
                    records, "fabric ↔ control", "control_bus"
                ),
                _connection_lane(
                    records, "fabric ↔ status", "status_bus"
                ),
                _connection_lane(
                    records, "fabric ↔ memory", "memory_bus"
                ),
            ],
            [
                "fabric post-state",
                _categorical_lane(
                    "AW join entries",
                    [item["pending_aw"] for item in fabrics],
                ),
                _categorical_lane(
                    "W join entries",
                    [item["pending_w"] for item in fabrics],
                ),
                _categorical_lane(
                    "active response owner",
                    [item["active_owner_count"] for item in fabrics],
                ),
                _categorical_lane(
                    "next fabric request id",
                    [item["next_request_id"] for item in fabrics],
                ),
            ],
        ],
        "head": {
            "text": (
                "AXI4-Lite one-manager fabric · route, response mux, DECERR"
            )
        },
        "foot": {
            "text": (
                "1 column = 1 completed SystemSession action · POST-STATE · "
                "not ACLK, pin timing, RTL or VCD"
            )
        },
        "config": {"hscale": 5},
    }


def _pack_causality(dot: str) -> str:
    return dot.replace(
        "splines=polyline];",
        'splines=polyline, pack=true, packmode="array_u2"];',
        1,
    )


def _published_readme() -> str:
    return """# AXI4-Lite single-manager, three-subordinate address fabric

This publication was built and executed by the named demo script.

## Canonical topology

![Canonical topology](topology.svg)

The canonical view keeps `fabric` as an explicit routing `VirtualDut`.  Four
binary `InterfaceConnection` instances connect concrete module ports; the
star shape alone does not supply decode or response-return behavior.

## Folded bus-strip view

![Bus-strip projection](bus-strip.svg)

This is a presentation projection of the same topology.  The long strip folds
the single-ingress fabric and labels its route windows; it is not a second
topology and does not turn AXI4-Lite into one implicit multi-drop connection.

## Fabric realization

![Fabric structure](fabric-structure.svg)

The shared VirtualDut projector exposes the upstream subordinate attachment,
three downstream manager attachments, address decoder/remap, pending owner,
and response mux.  These are constructed module-local components.

## Executed model steps

![Model-step view](model-steps.svg)

The first column holds `W` until the following `AW` arrives; the fifth column
holds `AW` until the following `W` arrives.  Completed writes and reads then
traverse the selected egress and return through the response mux.  The final
unmapped read returns `R/DECERR` locally and does not visit an endpoint.
Columns are completed semantic actions, not AXI clock cycles or a pin-level
golden trace.

## Recorded causality

![Causal graph](causality.svg)

The graph contains the accepted events and causal edges recorded by the
current system runtime.  It demonstrates this execution witness; it does not
claim exhaustive AXI4-Lite compliance or physical-timing equivalence.

Machine-readable execution is in [result.json](result.json), source IR is in
[sources](sources/), the generation boundary is in
[provenance.json](provenance.json), and [manifest.json](manifest.json) indexes
the complete publication.
"""


def _require_renderers() -> None:
    missing = []
    if shutil.which("dot") is None:
        missing.append("Graphviz 'dot'")
    wavedrom = REPOSITORY_ROOT / "node_modules" / ".bin" / "wavedrom"
    if not wavedrom.is_file():
        missing.append("WaveDrom (run 'npm ci' at repository root)")
    if missing:
        raise SystemExit("Missing renderer dependency: " + "; ".join(missing))


def _build_publication(directory: Path) -> Path:
    system, protocol = _build_system()
    session, state, records, responses = _execute(system)
    store = RunArtifactStore("vdut-axi4-lite-single-manager-fabric", directory)
    publisher = VisualizationPublisher(store)

    publisher.render_dot(
        "topology",
        system_topology_dot(system),
        kind="topology",
    )
    publisher.render_dot(
        "bus-strip",
        system_bus_strip_dot(
            system,
            fabric=FABRIC_NAME,
            title="AXI4-Lite · one manager / three subordinate bus view",
        ),
        kind="topology_projection",
    )
    publisher.render_dot(
        "fabric-structure",
        virtual_dut_structure_dot(system.virtual_duts[FABRIC_NAME]),
        kind="vdut_structure",
    )
    publisher.render_wave(
        "model-steps",
        _wavejson(records),
        kind="execution_step_view",
    )
    publisher.render_dot(
        "causality",
        _pack_causality(
            system_trace_dot(
                session.trace(state),
                title="AXI4-Lite single-manager fabric · recorded causality",
            )
        ),
        kind="causality",
    )
    store.write_json(
        "result.json",
        {
            "schema": (
                "protocol-model.showcase.axi4-lite-single-manager-fabric/v1"
            ),
            "system": {
                "name": system.name,
                "virtual_duts": list(system.virtual_duts),
                "connections": list(system.connections),
            },
            "address_windows": {
                "control": [CONTROL_BASE, CONTROL_BASE + REGISTER_BYTES],
                "status": [STATUS_BASE, STATUS_BASE + REGISTER_BYTES],
                "memory": [MEMORY_BASE, MEMORY_BASE + MEMORY_BYTES],
            },
            "steps": records,
            "manager_responses": [
                {
                    "kind": event.kind,
                    "payload": dict(event.payload),
                }
                for event in responses
            ],
            "assertions": {
                "fault_free": True,
                "control_readback": f"0x{CONTROL_VALUE:08x}",
                "status_readback": f"0x{STATUS_VALUE:08x}",
                "memory_readback": f"0x{MEMORY_VALUE:08x}",
                "unmapped_response": "DECERR",
                "final_quiescent": True,
            },
            "event_count": len(state.events),
            "causal_edges": [list(edge) for edge in state.causal_edges],
        },
        kind="execution_result",
    )
    store.write_text(
        "README.md",
        _published_readme(),
        kind="demo_guide",
        media_type="text/markdown",
    )
    store.write_json(
        "provenance.json",
        {
            "schema": "protocol-model.showcase.provenance/v1",
            "demo": DEMO_NAME,
            "source": (
                "showcase/demos/system/"
                "axi4_lite_single_manager_fabric/run.py"
            ),
            "command": (
                "python3 showcase/demos/system/"
                "axi4_lite_single_manager_fabric/run.py"
            ),
            "protocol_model_version": __version__,
            "execution_models": [
                "SystemSession",
                "SingleIngressAddressFabricBackend",
                "PassiveAddressSpaceBackend",
            ],
            "renderers": {
                "topology": "Graphviz + shared canonical system projection",
                "bus_strip": (
                    "Graphviz + shared folded single-ingress fabric projection"
                ),
                "vdut_structure": (
                    "Graphviz + shared VirtualDut structure projection"
                ),
                "model_steps": (
                    "WaveDrom + demo-local semantic post-state projection"
                ),
                "causality": "Graphviz + shared SystemTrace projection",
            },
            "presentation_boundary": (
                "canonical event and model-step execution; not AXI pins, "
                "cycle timing, RTL, VCD, or exhaustive compliance"
            ),
            "construction_boundary": (
                "one AddressRouterContract constructs the single-ingress "
                "fabric and declares SystemProtocol address resolution; "
                "the backend's typed boundary projection is checked before "
                "either object is registered"
            ),
        },
        kind="provenance",
    )
    return store.finalize(
        verdict="PASS",
        protocols=(
            protocol_record_from_system(system),
            protocol_record_from_interface(protocol),
        ),
        cases=(
            {
                "name": "route-three-address-windows",
                "expected": (
                    "control, status, and memory accesses select their "
                    "declared endpoint and return through the fabric"
                ),
                "observed": "PASS",
            },
            {
                "name": "unmapped-read",
                "expected": (
                    "the fabric returns AXI4-Lite DECERR without an egress"
                ),
                "observed": "PASS",
            },
        ),
        state={
            "event_count": len(state.events),
            "causal_edge_count": len(state.causal_edges),
            "manager_response_count": len(responses),
            "final_quiescent": True,
        },
        metadata={
            "publication": (
                "showcase/generated/system/axi4-lite-single-manager-fabric"
            ),
            "network_scope": (
                "non-coherent AXI4-Lite one-manager, three-subordinate "
                "address fabric"
            ),
            "raw_pin_capture": False,
            "time_basis": "model_step",
            "bus_strip_is_projection": True,
        },
        tool_version=__version__,
    )


def _publish(staged: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.with_name(f".{target.name}.previous")
    if previous.exists():
        shutil.rmtree(previous)
    if target.exists():
        target.replace(previous)
    try:
        staged.replace(target)
    except BaseException:
        if previous.exists() and not target.exists():
            previous.replace(target)
        raise
    else:
        if previous.exists():
            shutil.rmtree(previous)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Publish the AXI4-Lite single-manager address-fabric witness."
        )
    )
    parser.add_argument(
        "--publish-root",
        type=Path,
        default=SHOWCASE_ROOT / "generated" / "system",
        help="parent directory of the demo publication",
    )
    args = parser.parse_args(argv)
    publish_root = args.publish_root.expanduser().resolve()
    target = publish_root / DEMO_NAME
    build_root = publish_root.parent / ".build"
    build_root.mkdir(parents=True, exist_ok=True)

    _require_renderers()
    with TemporaryDirectory(
        prefix=f"{DEMO_NAME}-", dir=build_root
    ) as temporary:
        staged = Path(temporary) / DEMO_NAME
        manifest = _build_publication(staged)
        if not manifest.is_file():
            raise RuntimeError("staged demo has no manifest")
        for required in (
            "README.md",
            "result.json",
            "topology.svg",
            "sources/topology.dot",
            "bus-strip.svg",
            "sources/bus-strip.dot",
            "fabric-structure.svg",
            "sources/fabric-structure.dot",
            "model-steps.svg",
            "sources/model-steps.json",
            "causality.svg",
            "sources/causality.dot",
            "provenance.json",
        ):
            if not (staged / required).is_file():
                raise RuntimeError(f"staged demo lacks {required}")
        _publish(staged, target)

    try:
        build_root.rmdir()
    except OSError:
        pass
    print(f"Published AXI4-Lite single-manager fabric demo: {target}")
    print(f"Manifest: {target / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
