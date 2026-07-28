#!/usr/bin/env python3
"""Publish an AXI4 one-manager, two-subordinate read-return witness."""

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
    build_axi4_address_space_vdut,
)
from protocol_model.integrations.recipes.amba.fabrics import (  # noqa: E402
    Axi4ReadRouteTableProfile,
    build_axi4_read_demux_vdut,
)
from protocol_model.integrations.backends.amba.axi.axi4.read import (  # noqa: E402
    Axi4ReadCrossbarState,
)
from protocol_model.protocols.amba.axi.axi4 import (  # noqa: E402
    Axi4Config,
    build_axi4_read_only_profile,
)
from protocol_model.semantics import CanonicalEvent  # noqa: E402
from protocol_model.system import (  # noqa: E402
    AddressClaim,
    AddressRouterContract,
    AddressWindow,
    DutAdvanceAction,
    SystemAction,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut import (  # noqa: E402
    AddressRoute,
    AddressSpace,
    InterfacePort,
    MemoryRegion,
    SteppedEmissionProfile,
    VirtualDut,
)
from protocol_model.virtual_dut.backend import (  # noqa: E402
    CaptureBackend,
    CaptureState,
)
from protocol_model.visualization import (  # noqa: E402
    VisualizationPublisher,
    system_topology_dot,
    system_trace_dot,
)


DEMO_NAME = "axi4-single-manager-read-demux"
SYSTEM_NAME = "axi4_single_manager_read_demux"
FABRIC_NAME = "read_fabric"

TARGET0_BASE = 0x1000
TARGET1_BASE = 0x2000
TARGET_BYTES = 0x100


def _manager(protocol) -> VirtualDut:
    return VirtualDut(
        "manager",
        {"axi": InterfacePort("axi", protocol, "manager")},
        backend=CaptureBackend(),
        description="scenario-driven AXI4 manager boundary",
    )


def _target(
    name: str,
    protocol,
    words: tuple[int, ...],
) -> VirtualDut:
    initial_content = b"".join(
        word.to_bytes(4, byteorder="little") for word in words
    )
    return build_axi4_address_space_vdut(
        name,
        protocol,
        AddressSpace(
            (
                MemoryRegion(
                    f"{name}_ram",
                    TARGET_BYTES,
                    initial_content=initial_content,
                ),
            )
        ),
        response_profile=SteppedEmissionProfile(capacity_events=16),
    )


def _build_system():
    protocol = build_axi4_read_only_profile(
        Axi4Config(data_width=32, id_width=3)
    )
    routes = (
        AddressRoute("target0", TARGET0_BASE, TARGET_BYTES, "m0", 0),
        AddressRoute("target1", TARGET1_BASE, TARGET_BYTES, "m1", 0),
    )
    router = AddressRouterContract(
        "read_address_map",
        FABRIC_NAME,
        ("s_axi",),
        ("m0", "m1"),
        routes,
    )

    builder = SystemProtocolBuilder(SYSTEM_NAME)
    for dut in (
        _manager(protocol),
        _target("target0", protocol, (0x11, 0x12, 0x13, 0x14)),
        _target("target1", protocol, (0x21, 0x22, 0x23, 0x24)),
    ):
        builder.add_dut(dut)
    builder.construct_address_router(
        router,
        lambda contract: build_axi4_read_demux_vdut(
            contract.router,
            protocol,
            contract.egress_ports,
            contract.routes,
            ingress_port=contract.ingress_ports[0],
            table_profile=Axi4ReadRouteTableProfile(
                active_id_capacity=2,
                outstanding_bursts_per_id=4,
            ),
        ),
    )
    builder.connect(
        "manager_bus",
        protocol,
        {
            "manager": VirtualDutPortRef("manager", "axi"),
            "subordinate": VirtualDutPortRef(FABRIC_NAME, "s_axi"),
        },
    )
    for index in range(2):
        target = f"target{index}"
        builder.connect(
            f"{target}_bus",
            protocol,
            {
                "manager": VirtualDutPortRef(FABRIC_NAME, f"m{index}"),
                "subordinate": VirtualDutPortRef(target, "axi"),
            },
        )
        builder.add_address_claim(
            AddressClaim(
                f"{target}_local",
                VirtualDutPortRef(target, "axi"),
                AddressWindow(0, TARGET_BYTES),
            )
        )
    return builder.build(), protocol


def _ar(read_id: int, address: int, *, length: int = 0) -> CanonicalEvent:
    return CanonicalEvent(
        "AR",
        read_id,
        {
            "addr": address,
            "len": length,
            "size": 2,
            "burst": "INCR",
            "lock": 0,
            "cache": 0,
            "prot": 0,
            "qos": 0,
            "region": 0,
        },
    )


def _issue(read_id: int, address: int, *, length: int = 0) -> SystemAction:
    return SystemAction(
        VirtualDutPortRef("manager", "axi"),
        _ar(read_id, address, length=length),
    )


def _event_summary(event: CanonicalEvent) -> str:
    if event.kind == "AR":
        return (
            f"AR id={event.key} @0x{int(event.payload['addr']):04x} "
            f"beats={int(event.payload['len']) + 1}"
        )
    if event.kind == "R":
        suffix = " last" if bool(event.payload["last"]) else ""
        return (
            f"R id={event.key} data=0x{int(event.payload['data']):02x}"
            f"{suffix}"
        )
    return f"{event.kind} id={event.key}"


def _fabric_snapshot(state) -> dict[str, object]:
    fabric = state.dut_states[FABRIC_NAME]
    if not isinstance(fabric, Axi4ReadCrossbarState):
        raise TypeError("demo expected Axi4ReadCrossbarState")
    grouped: dict[int, list[object]] = {}
    for item in fabric.pending:
        grouped.setdefault(item.upstream_id, []).append(item)
    return {
        "active_ids": len(grouped),
        "owners": [
            {
                "rid": read_id,
                "egress": entries[0].egress_port,
                "remaining_beats": [
                    entry.remaining_beats for entry in entries
                ],
            }
            for read_id, entries in sorted(grouped.items())
        ],
    }


def _owner_summary(snapshot: dict[str, object]) -> str:
    owners = snapshot["owners"]
    if not owners:
        return "empty"
    return " · ".join(
        f"RID{owner['rid']}→{owner['egress']}"
        f"{owner['remaining_beats']}"
        for owner in owners
    )


def _emission_record(item) -> dict[str, object]:
    return {
        "index": item.index,
        "connection": item.connection,
        "source": item.source.qualified_name,
        "destination": item.destination.qualified_name,
        "kind": item.event.kind,
        "key": item.event.key,
        "payload": dict(item.event.payload),
    }


def _record(label: str, action: str, transition) -> dict[str, object]:
    responses = [
        item.event
        for item in transition.emissions
        if item.destination == VirtualDutPortRef("manager", "axi")
        and item.event.kind == "R"
    ]
    blocked = transition.blocked
    return {
        "label": label,
        "action": action,
        "verdict": (
            "accepted"
            if blocked is None
            else f"BLOCK · {blocked.resource}"
        ),
        "blocked": (
            None
            if blocked is None
            else {
                "resource": blocked.resource,
                "reason": blocked.reason,
                "capacity": blocked.capacity,
            }
        ),
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
            else " + ".join(_event_summary(event) for event in responses)
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
            "S0 · issue RID1 to target0",
            "AR RID1 target0 · 2 beats",
            _issue(1, TARGET0_BASE, length=1),
            False,
        ),
        (
            "S1 · issue RID2 to target1",
            "AR RID2 target1 · 2 beats",
            _issue(2, TARGET1_BASE, length=1),
            False,
        ),
        (
            "S2 · target1 returns first beat",
            "advance target1",
            DutAdvanceAction("target1"),
            False,
        ),
        (
            "S3 · target0 returns first beat",
            "advance target0",
            DutAdvanceAction("target0"),
            False,
        ),
        (
            "S4 · target1 completes RID2",
            "advance target1",
            DutAdvanceAction("target1"),
            False,
        ),
        (
            "S5 · target0 completes RID1",
            "advance target0",
            DutAdvanceAction("target0"),
            False,
        ),
        (
            "S6 · issue RID3 to target0",
            "AR RID3 target0",
            _issue(3, TARGET0_BASE + 8),
            False,
        ),
        (
            "S7 · same RID targets another device",
            "AR RID3 target1 · first attempt",
            _issue(3, TARGET1_BASE + 8),
            True,
        ),
        (
            "S8 · target0 releases RID3",
            "advance target0",
            DutAdvanceAction("target0"),
            False,
        ),
        (
            "S9 · retry RID3 to target1",
            "AR RID3 target1 · retry",
            _issue(3, TARGET1_BASE + 8),
            False,
        ),
        (
            "S10 · target1 completes retry",
            "advance target1",
            DutAdvanceAction("target1"),
            False,
        ),
    )

    for label, action_name, action, expect_blocked in actions:
        transition = session.step(state, action)
        records.append(_record(label, action_name, transition))
        if transition.fault is not None:
            raise RuntimeError(
                f"read-demux witness failed at {label}: "
                f"{transition.fault.rule}: {transition.fault.reason}"
            )
        if (transition.blocked is not None) is not expect_blocked:
            raise RuntimeError(
                f"unexpected admission result at {label}: "
                f"blocked={transition.blocked is not None}"
            )
        state = transition.state

    manager = state.dut_states["manager"]
    if not isinstance(manager, CaptureState):
        raise TypeError("demo expected CaptureState")
    responses = tuple(
        item.event for item in manager.received if item.event.kind == "R"
    )
    observed = tuple(
        (
            int(event.key),
            int(event.payload["data"]),
            bool(event.payload["last"]),
        )
        for event in responses
    )
    expected = (
        (2, 0x21, False),
        (1, 0x11, False),
        (2, 0x22, True),
        (1, 0x12, True),
        (3, 0x13, True),
        (3, 0x23, True),
    )
    if observed != expected:
        raise RuntimeError(
            f"manager response mismatch: expected {expected!r}, "
            f"got {observed!r}"
        )
    if not session.is_quiescent(state):
        raise RuntimeError("read-demux witness did not return to quiescence")
    return session, state, records, responses


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
                _event_summary(
                    CanonicalEvent(
                        str(item["kind"]),
                        item["key"],
                        dict(item["payload"]),
                    )
                )
                for item in events
            )
        )
    return _categorical_lane(name, values)


def _wavejson(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "signal": [
            _categorical_lane(
                "MODEL STEP · not ACLK",
                [f"S{index}" for index in range(len(records))],
            ),
            [
                "scenario",
                _categorical_lane(
                    "attempted action",
                    [record["action"] for record in records],
                ),
                _categorical_lane(
                    "admission",
                    [record["verdict"] for record in records],
                ),
                _categorical_lane(
                    "manager R",
                    [record["manager_response"] for record in records],
                ),
            ],
            [
                "accepted interface events",
                _connection_lane(
                    records, "manager ↔ fabric", "manager_bus"
                ),
                _connection_lane(
                    records, "fabric ↔ target0", "target0_bus"
                ),
                _connection_lane(
                    records, "fabric ↔ target1", "target1_bus"
                ),
            ],
            [
                "fabric post-state",
                _categorical_lane(
                    "active RID entries",
                    [record["fabric"]["active_ids"] for record in records],
                ),
                _categorical_lane(
                    "RID → egress [remaining beats]",
                    [
                        _owner_summary(record["fabric"])
                        for record in records
                    ],
                ),
            ],
        ],
        "head": {
            "text": (
                "AXI4 one-manager read demux · multi-device R return"
            )
        },
        "foot": {
            "text": (
                "1 column = 1 attempted SystemSession action · POST-STATE · "
                "BLOCK rolls back the attempted action"
            )
        },
        "config": {"hscale": 4},
    }


def _published_readme() -> str:
    return """# AXI4 single-manager, two-subordinate read fabric

This publication was built and executed by the named demo script.

## Canonical topology

![Canonical topology](topology.svg)

The topology contains one manager boundary, one explicit read-fabric
`VirtualDut`, two memory endpoints, and three binary AXI4
`InterfaceConnection` instances.  The star shape is a consequence of the
connections; decode and response-return behavior comes from the fabric backend.

## Executed model steps

![Model-step view](model-steps.svg)

RID 1 and RID 2 are simultaneously owned by different output ports.  The
targets are advanced in alternating order, producing the legal return sequence
`RID2, RID1, RID2/RLAST, RID1/RLAST`.  Later, RID 3 is locked to target 0; an
attempt to send that RID to target 1 is blocked and leaves the state unchanged.
The retry succeeds after target 0 returns `RLAST`.

The columns are semantic actions, not ACLK cycles or a pin-level golden trace.
The table is a sparse model data structure; its RTL mapping is deliberately not
fixed by this example.

## Recorded causality

![Causal graph](causality.svg)

Only accepted interface events enter the causal graph.  The blocked first
attempt for RID 3 is retained in `result.json` as an admission result but has no
committed interface event.

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
    store = RunArtifactStore("vdut-axi4-read-demux", directory)
    publisher = VisualizationPublisher(store)

    publisher.render_dot(
        "topology",
        system_topology_dot(system),
        kind="topology",
    )
    publisher.render_wave(
        "model-steps",
        _wavejson(records),
        kind="execution_step_view",
    )
    publisher.render_dot(
        "causality",
        system_trace_dot(
            session.trace(state),
            title="AXI4 read demux · recorded causality",
        ),
        kind="causality",
    )
    store.write_json(
        "result.json",
        {
            "schema": "protocol-model.showcase.axi4-read-demux/v1",
            "system": {
                "name": system.name,
                "virtual_duts": list(system.virtual_duts),
                "connections": list(system.connections),
            },
            "address_windows": {
                "target0": [TARGET0_BASE, TARGET0_BASE + TARGET_BYTES],
                "target1": [TARGET1_BASE, TARGET1_BASE + TARGET_BYTES],
            },
            "route_table_profile": {
                "active_id_capacity": 2,
                "outstanding_bursts_per_id": 4,
            },
            "steps": records,
            "manager_responses": [
                {
                    "kind": event.kind,
                    "rid": event.key,
                    "payload": dict(event.payload),
                }
                for event in responses
            ],
            "assertions": {
                "fault_free": True,
                "different_rids_return_independently": True,
                "same_rid_cross_target_blocks": True,
                "same_rid_retry_after_rlast": True,
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
                "axi4_single_manager_read_demux/run.py"
            ),
            "command": (
                "python3 showcase/demos/system/"
                "axi4_single_manager_read_demux/run.py"
            ),
            "protocol_model_version": __version__,
            "execution_models": [
                "SystemSession",
                "Axi4ReadCrossbarBackend (one ingress)",
                "SteppedEmissionBackend",
                "PassiveAddressSpaceBackend",
            ],
            "renderers": {
                "topology": "Graphviz + shared system projection",
                "model_steps": (
                    "WaveDrom + demo-local semantic post-state projection"
                ),
                "causality": "Graphviz + shared SystemTrace projection",
            },
            "presentation_boundary": (
                "canonical AXI4 AR/R events and model steps; not AXI pins, "
                "cycle timing, RTL, VCD, or exhaustive compliance"
            ),
            "construction_boundary": (
                "one AddressRouterContract constructs and validates the "
                "single-ingress AXI4 read fabric boundary"
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
                "name": "different-rid-multi-device-return",
                "expected": (
                    "two devices may return different RIDs independently"
                ),
                "observed": "PASS",
            },
            {
                "name": "same-rid-destination-lock",
                "expected": (
                    "a same-RID request for another device blocks until "
                    "the prior RLAST and then succeeds on retry"
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
                "showcase/generated/system/axi4-single-manager-read-demux"
            ),
            "network_scope": (
                "non-coherent Full AXI4 one-manager, two-subordinate "
                "read-path fabric"
            ),
            "raw_pin_capture": False,
            "time_basis": "model_step",
            "implemented_channels": ["AR", "R"],
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
        description="Publish the AXI4 single-manager read-demux witness."
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
    print(f"Published AXI4 read-demux demo: {target}")
    print(f"Manifest: {target / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
