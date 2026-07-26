#!/usr/bin/env python3
"""Publish a transaction-level AXI4 read 2x4 crossbar witness."""

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
    build_axi4_read_crossbar_vdut,
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
    DiagramDetail,
    VisualizationPublisher,
    interconnect_interface_map_dot,
    project_address_interconnect,
    system_topology_dot,
    system_trace_dot,
)


DEMO_NAME = "axi4-read-2x4-crossbar"
SYSTEM_NAME = "axi4_read_two_by_four_crossbar"
CROSSBAR_NAME = "crossbar"
TARGET_BASES = (0x1000, 0x2000, 0x3000, 0x4000)
TARGET_BYTES = 0x100


def _manager(name: str, protocol) -> VirtualDut:
    return VirtualDut(
        name,
        {"axi": InterfacePort("axi", protocol, "manager")},
        backend=CaptureBackend(),
        description="scenario-driven AXI4 manager boundary",
    )


def _target(
    name: str,
    protocol,
    first_word: int,
) -> VirtualDut:
    content = b"".join(
        word.to_bytes(4, byteorder="little")
        for word in range(first_word, first_word + 4)
    )
    return build_axi4_address_space_vdut(
        name,
        protocol,
        AddressSpace(
            (
                MemoryRegion(
                    f"{name}_ram",
                    TARGET_BYTES,
                    initial_content=content,
                ),
            )
        ),
        response_profile=SteppedEmissionProfile(capacity_events=16),
    )


def _build_system():
    protocol = build_axi4_read_only_profile(
        Axi4Config(data_width=32, id_width=3)
    )
    routes = tuple(
        AddressRoute(
            f"target{index}",
            base,
            TARGET_BYTES,
            f"m{index}",
            output_base_address=0,
        )
        for index, base in enumerate(TARGET_BASES)
    )
    router = AddressRouterContract(
        "read_address_map",
        CROSSBAR_NAME,
        ("s0", "s1"),
        tuple(f"m{index}" for index in range(4)),
        routes,
    )

    builder = SystemProtocolBuilder(SYSTEM_NAME)
    for dut in (
        _manager("manager0", protocol),
        _manager("manager1", protocol),
        *(
            _target(
                f"target{index}",
                protocol,
                (index + 1) * 0x10 + 1,
            )
            for index in range(4)
        ),
    ):
        builder.add_dut(dut)
    builder.construct_address_router(
        router,
        lambda contract: build_axi4_read_crossbar_vdut(
            contract.router,
            protocol,
            contract.ingress_ports,
            contract.egress_ports,
            contract.routes,
            table_profile=Axi4ReadRouteTableProfile(
                active_id_capacity=4,
                outstanding_bursts_per_id=4,
            ),
        ),
    )
    for index in range(2):
        builder.connect(
            f"manager{index}_bus",
            protocol,
            {
                "manager": VirtualDutPortRef(f"manager{index}", "axi"),
                "subordinate": VirtualDutPortRef(
                    CROSSBAR_NAME, f"s{index}"
                ),
            },
        )
    for index in range(4):
        builder.connect(
            f"target{index}_bus",
            protocol,
            {
                "manager": VirtualDutPortRef(
                    CROSSBAR_NAME, f"m{index}"
                ),
                "subordinate": VirtualDutPortRef(
                    f"target{index}", "axi"
                ),
            },
        )
        builder.add_address_claim(
            AddressClaim(
                f"target{index}_local",
                VirtualDutPortRef(f"target{index}", "axi"),
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


def _issue(
    manager: int,
    read_id: int,
    address: int,
    *,
    length: int = 0,
) -> SystemAction:
    return SystemAction(
        VirtualDutPortRef(f"manager{manager}", "axi"),
        _ar(read_id, address, length=length),
    )


def _event_summary(event: CanonicalEvent) -> str:
    if event.kind == "AR":
        return (
            f"AR R{event.key}@{int(event.payload['addr']):04x} "
            f"×{int(event.payload['len']) + 1}"
        )
    if event.kind == "R":
        suffix = "/L" if bool(event.payload["last"]) else ""
        return f"R{event.key}={int(event.payload['data']):02x}{suffix}"
    return f"{event.kind} R{event.key}"


def _state_snapshot(state) -> dict[str, object]:
    crossbar = state.dut_states[CROSSBAR_NAME]
    if not isinstance(crossbar, Axi4ReadCrossbarState):
        raise TypeError("demo expected Axi4ReadCrossbarState")

    route_locks: dict[tuple[str, int], list[object]] = {}
    owner_queues: dict[tuple[str, int], list[object]] = {}
    for item in crossbar.pending:
        route_locks.setdefault(
            (item.ingress_port, item.upstream_id), []
        ).append(item)
        owner_queues.setdefault(
            (item.egress_port, item.downstream_id), []
        ).append(item)
    return {
        "pending": [
            {
                "serial": item.serial,
                "ingress": item.ingress_port,
                "upstream_rid": item.upstream_id,
                "egress": item.egress_port,
                "downstream_rid": item.downstream_id,
                "remaining_beats": item.remaining_beats,
            }
            for item in crossbar.pending
        ],
        "route_locks": [
            {
                "ingress": key[0],
                "rid": key[1],
                "egress": items[0].egress_port,
                "bursts": len(items),
            }
            for key, items in sorted(route_locks.items())
        ],
        "owner_queues": [
            {
                "egress": key[0],
                "downstream_rid": key[1],
                "owners": [item.ingress_port for item in items],
            }
            for key, items in sorted(owner_queues.items())
        ],
    }


def _focused_route_lock(
    snapshot: dict[str, object],
    *,
    ingress: str,
    read_id: int,
) -> str:
    for item in snapshot["route_locks"]:
        if item["ingress"] == ingress and item["rid"] == read_id:
            return str(item["egress"]).replace("m", "T", 1)
    return "—"


def _focused_owner_queue(
    snapshot: dict[str, object],
    *,
    egress: str,
    read_id: int,
) -> str:
    for item in snapshot["owner_queues"]:
        if (
            item["egress"] == egress
            and item["downstream_rid"] == read_id
        ):
            return "→".join(
                str(owner).replace("s", "M", 1)
                for owner in item["owners"]
            )
    return "—"


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
    manager_responses = {0: [], 1: []}
    for item in transition.emissions:
        for manager in range(2):
            if (
                item.destination
                == VirtualDutPortRef(f"manager{manager}", "axi")
                and item.event.kind == "R"
            ):
                manager_responses[manager].append(
                    _event_summary(item.event)
                )
    blocked = transition.blocked
    return {
        "label": label,
        "action": action,
        "admission": (
            "OK"
            if blocked is None
            else "BLOCK · RID route lock"
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
        "manager0_response": " + ".join(manager_responses[0]) or "—",
        "manager1_response": " + ".join(manager_responses[1]) or "—",
        "crossbar": _state_snapshot(transition.state),
        "emissions": [
            _emission_record(item) for item in transition.emissions
        ],
    }


def _captured(state, manager: int) -> tuple[CanonicalEvent, ...]:
    capture = state.dut_states[f"manager{manager}"]
    if not isinstance(capture, CaptureState):
        raise TypeError("demo expected CaptureState")
    return tuple(item.event for item in capture.received)


def _execute(system):
    session = system.open_session()
    state = session.initial_state()
    records: list[dict[str, object]] = []
    actions = (
        (
            "S0 · manager0 RID1 opens target0 burst",
            "M0 R1→T0 ×2",
            _issue(0, 1, 0x1000, length=1),
            False,
        ),
        (
            "S1 · manager1 uses the same RID at target3",
            "M1 R1→T3",
            _issue(1, 1, 0x4000),
            False,
        ),
        (
            "S2 · manager0 RID2 enters shared target2 stream",
            "M0 R2→T2",
            _issue(0, 2, 0x3000),
            False,
        ),
        (
            "S3 · manager1 same RID follows at target2",
            "M1 R2→T2",
            _issue(1, 2, 0x3004),
            False,
        ),
        (
            "S4 · manager0 cannot redirect active RID1",
            "M0 R1→T1 try 1",
            _issue(0, 1, 0x2000),
            True,
        ),
        (
            "S5 · target3 returns manager1 RID1",
            "advance T3",
            DutAdvanceAction("target3"),
            False,
        ),
        (
            "S6 · target2 owner FIFO returns manager0 first",
            "advance T2",
            DutAdvanceAction("target2"),
            False,
        ),
        (
            "S7 · target2 owner FIFO advances to manager1",
            "advance T2",
            DutAdvanceAction("target2"),
            False,
        ),
        (
            "S8 · target0 emits first RID1 beat",
            "advance T0 beat 1",
            DutAdvanceAction("target0"),
            False,
        ),
        (
            "S9 · route lock remains until RLAST",
            "M0 R1→T1 try 2",
            _issue(0, 1, 0x2000),
            True,
        ),
        (
            "S10 · target0 RLAST releases manager0 RID1",
            "advance T0 RLAST",
            DutAdvanceAction("target0"),
            False,
        ),
        (
            "S11 · manager0 retries RID1 at target1",
            "M0 R1→T1 retry",
            _issue(0, 1, 0x2000),
            False,
        ),
        (
            "S12 · target1 completes the retry",
            "advance T1",
            DutAdvanceAction("target1"),
            False,
        ),
    )

    for label, action_name, action, expect_blocked in actions:
        transition = session.step(state, action)
        records.append(_record(label, action_name, transition))
        if transition.fault is not None:
            raise RuntimeError(
                f"2x4 witness failed at {label}: "
                f"{transition.fault.rule}: {transition.fault.reason}"
            )
        if (transition.blocked is not None) is not expect_blocked:
            raise RuntimeError(
                f"unexpected admission result at {label}: "
                f"blocked={transition.blocked is not None}"
            )
        state = transition.state

    manager0 = tuple(
        (
            int(event.key),
            int(event.payload["data"]),
            bool(event.payload["last"]),
        )
        for event in _captured(state, 0)
    )
    manager1 = tuple(
        (
            int(event.key),
            int(event.payload["data"]),
            bool(event.payload["last"]),
        )
        for event in _captured(state, 1)
    )
    expected0 = (
        (2, 0x31, True),
        (1, 0x11, False),
        (1, 0x12, True),
        (1, 0x21, True),
    )
    expected1 = ((1, 0x41, True), (2, 0x32, True))
    if manager0 != expected0 or manager1 != expected1:
        raise RuntimeError(
            "manager response mismatch: "
            f"M0 expected {expected0!r}, got {manager0!r}; "
            f"M1 expected {expected1!r}, got {manager1!r}"
        )
    if not session.is_quiescent(state):
        raise RuntimeError("2x4 witness did not return to quiescence")
    plan = system.elaborate().address_plan
    if plan is None or len(plan.paths) != 8:
        raise RuntimeError("2x4 address plan did not resolve eight paths")
    return session, state, records, manager0, manager1


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
                    [record["admission"] for record in records],
                ),
                _categorical_lane(
                    "manager0 R",
                    [record["manager0_response"] for record in records],
                ),
                _categorical_lane(
                    "manager1 R",
                    [record["manager1_response"] for record in records],
                ),
            ],
            [
                "accepted interface events",
                _connection_lane(records, "manager0 ↔ crossbar", "manager0_bus"),
                _connection_lane(records, "manager1 ↔ crossbar", "manager1_bus"),
                *(
                    _connection_lane(
                        records,
                        f"crossbar ↔ target{index}",
                        f"target{index}_bus",
                    )
                    for index in range(4)
                ),
            ],
            [
                "crossbar post-state",
                _categorical_lane(
                    "pending burst count",
                    [len(record["crossbar"]["pending"]) for record in records],
                ),
                _categorical_lane(
                    "M0/R1 destination lock",
                    [
                        _focused_route_lock(
                            record["crossbar"], ingress="s0", read_id=1
                        )
                        for record in records
                    ],
                ),
                _categorical_lane(
                    "M1/R1 destination lock",
                    [
                        _focused_route_lock(
                            record["crossbar"], ingress="s1", read_id=1
                        )
                        for record in records
                    ],
                ),
                _categorical_lane(
                    "T2/R2 return owners",
                    [
                        _focused_owner_queue(
                            record["crossbar"], egress="m2", read_id=2
                        )
                        for record in records
                    ],
                ),
            ],
        ],
        "head": {
            "text": "AXI4 read 2×4 crossbar · source and return ownership"
        },
        "foot": {
            "text": (
                "1 column = 1 attempted SystemSession action · POST-STATE · "
                "transaction-level witness, not ACLK or pin arbitration"
            )
        },
        "config": {"hscale": 4},
    }


def _published_readme() -> str:
    return """# AXI4 read 2×4 crossbar · executable witness

This publication was built and executed by the named demo script.

## Canonical topology

![Canonical topology](topology.svg)

Two manager boundaries and four memory targets are connected through one
explicit crossbar `VirtualDut`.  The same parameterized builder accepts any
non-empty ingress and egress tuples; 2×4 is an instance chosen to make the
independence of N and M visible.  System address resolution closes two
ingresses across four route windows, producing eight resolved paths.

## Interconnect interface map

![Interconnect interface map](interconnect-interface-map.svg)

The typed map expands only the crossbar boundary.  It shows the two ingress
and four egress ports, each port's AXI4 read-only role, and the four resolved
system-to-local address remaps.  The central rectangle does not assert an
internal lane count or physical crosspoint implementation.

## Executed model steps

![Model-step view](model-steps.svg)

The crossbar owns one sparse pending-read ledger.  Two views are derived from
the same entries:

- `(ingress, RID) → egress` prevents one manager's active RID from changing
  target before its previous `RLAST`;
- `(egress, downstream RID) → FIFO[ingress]` returns colliding raw IDs to the
  manager whose AR entered that downstream ID stream first.

S2 and S3 place manager0/RID2 followed by manager1/RID2 at target2.  S6 and S7
return them in that owner order.  Manager1/RID1 independently completes from
target3 at S5.  Manager0/RID1 remains locked to target0 after its first beat,
so both S4 and S9 are blocked; S11 succeeds after the target0 `RLAST` at S10.

Canonical events already represent accepted transfers.  Their submission
order is this witness's grant order; the model does not prescribe an RTL
arbiter or simultaneous-pin timing.

## Recorded causality

![Causal graph](causality.svg)

Blocked attempts leave no accepted interface event and are retained in
`result.json`.  Accepted AR/R events and the causal edges currently recorded
by `SystemSession` appear here.

## Current profile boundary

The `raw-ID-serialized` profile preserves ARID downstream.  Different managers
using the same RID at one target therefore share one legal downstream ordering
stream.  This may serialize otherwise independent work, but it does not lose
ordinary read ownership.  Multi-ingress exclusive reads are rejected because
exclusive identity must be source-qualified.  A later prefix/remap policy can
populate the ledger's separate `downstream_id` field without changing the
upstream ordering key or return-owner mechanism.

Machine-readable execution is in [result.json](result.json), source IR is in
[sources](sources/), generation boundaries are in
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
    session, state, records, manager0, manager1 = _execute(system)
    store = RunArtifactStore("vdut-axi4-read-2x4-crossbar", directory)
    publisher = VisualizationPublisher(store)
    interface_map = project_address_interconnect(
        system.elaborate(), interconnect=CROSSBAR_NAME
    )
    interface_map_detail = DiagramDetail.STANDARD
    interface_map_descriptor = interface_map.descriptor(
        detail=interface_map_detail
    )

    publisher.render_dot(
        "topology",
        system_topology_dot(system),
        kind="topology",
    )
    publisher.render_dot(
        "interconnect-interface-map",
        interconnect_interface_map_dot(
            interface_map,
            detail=interface_map_descriptor.detail,
            title="AXI4 read-only 2×4 · interface boundary view",
        ),
        kind=interface_map_descriptor.view_kind.value,
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
            title="AXI4 read 2×4 crossbar · recorded causality",
        ),
        kind="causality",
    )
    store.write_json(
        "result.json",
        {
            "schema": "protocol-model.showcase.axi4-read-2x4-crossbar/v1",
            "system": {
                "name": system.name,
                "virtual_duts": list(system.virtual_duts),
                "connections": list(system.connections),
                "resolved_address_paths": 8,
            },
            "address_windows": {
                f"target{index}": [base, base + TARGET_BYTES]
                for index, base in enumerate(TARGET_BASES)
            },
            "id_policy": "raw-id-serialized",
            "route_table_profile": {
                "active_id_capacity_per_ingress": 4,
                "outstanding_bursts_per_id": 4,
            },
            "steps": records,
            "manager_responses": {
                "manager0": [list(item) for item in manager0],
                "manager1": [list(item) for item in manager1],
            },
            "assertions": {
                "fault_free": True,
                "same_raw_rid_owner_fifo": True,
                "manager_id_namespaces_are_distinct": True,
                "same_manager_route_lock_until_rlast": True,
                "blocked_steps_rolled_back": True,
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
                "showcase/demos/system/axi4_read_2x4_crossbar/run.py"
            ),
            "command": (
                "python3 "
                "showcase/demos/system/axi4_read_2x4_crossbar/run.py"
            ),
            "protocol_model_version": __version__,
            "execution_models": [
                "SystemSession",
                "Axi4ReadCrossbarBackend",
                "SteppedEmissionBackend",
                "PassiveAddressSpaceBackend",
            ],
            "renderers": {
                "topology": "Graphviz + shared system projection",
                "interconnect_interface_map": (
                    "Graphviz + shared typed address-interconnect projection"
                ),
                "model_steps": (
                    "WaveDrom + demo-local semantic post-state projection"
                ),
                "causality": "Graphviz + shared SystemTrace projection",
            },
            "interconnect_interface_map": {
                "view_kind": interface_map_descriptor.view_kind.value,
                "scope": interface_map_descriptor.scope.value,
                "evidence_basis": (
                    interface_map_descriptor.evidence_basis.value
                ),
                "projection_intent": (
                    interface_map_descriptor.projection_intent.value
                ),
                "time_basis": interface_map_descriptor.time_basis.value,
                "source_schema": interface_map_descriptor.source_schema,
                "detail": interface_map_descriptor.detail.value,
            },
            "presentation_boundary": (
                "accepted canonical AXI4 AR/R events and model steps; "
                "not pin-level arbitration, ACLK timing, RTL, or VCD"
            ),
            "construction_boundary": (
                "one AddressRouterContract constructs and checks a "
                "parameterized two-ingress/four-egress read crossbar"
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
                "name": "same-raw-rid-return-owner",
                "expected": (
                    "two managers sharing one downstream RID receive their "
                    "responses in downstream acceptance order"
                ),
                "observed": "PASS",
            },
            {
                "name": "same-manager-destination-lock",
                "expected": (
                    "one manager cannot redirect an active RID until its "
                    "prior RLAST, then retry succeeds"
                ),
                "observed": "PASS",
            },
        ),
        state={
            "event_count": len(state.events),
            "causal_edge_count": len(state.causal_edges),
            "manager0_response_count": len(manager0),
            "manager1_response_count": len(manager1),
            "final_quiescent": True,
        },
        metadata={
            "publication": (
                "showcase/generated/system/axi4-read-2x4-crossbar"
            ),
            "network_scope": (
                "non-coherent AXI4 read-only AR/R two-manager/"
                "four-subordinate crossbar"
            ),
            "implemented_channels": ["AR", "R"],
            "id_policy": "raw-id-serialized",
            "raw_pin_capture": False,
            "time_basis": "model_step",
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
        description="Publish the AXI4 read 2x4 crossbar witness."
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
            "interconnect-interface-map.svg",
            "sources/interconnect-interface-map.dot",
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
    print(f"Published AXI4 read 2x4 crossbar demo: {target}")
    print(f"Manifest: {target / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
