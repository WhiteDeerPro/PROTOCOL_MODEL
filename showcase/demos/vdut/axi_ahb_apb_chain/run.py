#!/usr/bin/env python3
"""Execute and publish a two-bridge AMBA peripheral network.

The demo is intentionally transaction-level.  It demonstrates cross-protocol
composition, ownership, address routing, and completion return; it does not
invent AXI/AHB/APB pin cycles or a coherent network contract.
"""

from __future__ import annotations

import argparse
import json
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
from protocol_model.integrations.recipes.amba.bridges import (  # noqa: E402
    build_amba_serial_bridge_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints import (  # noqa: E402
    build_apb_address_space_vdut,
)
from protocol_model.integrations.recipes.amba.fabrics import (  # noqa: E402
    build_apb_address_fabric_vdut,
)
from protocol_model.protocols.amba.ahb.ahb_lite import (  # noqa: E402
    build_ahb_lite_interface,
)
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface  # noqa: E402
from protocol_model.protocols.amba.axi.axi4_lite import (  # noqa: E402
    build_axi4_lite_interface,
)
from protocol_model.semantics import CanonicalEvent  # noqa: E402
from protocol_model.system import (  # noqa: E402
    InterfaceConnection,
    SystemAction,
    SystemProtocol,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.address import (  # noqa: E402
    AddressSpace,
    RegisterRegion,
    RegisterSpec,
)
from protocol_model.virtual_dut.backend import CaptureBackend  # noqa: E402
from protocol_model.virtual_dut.boundary import (  # noqa: E402
    InterfacePort,
    VirtualDut,
)
from protocol_model.virtual_dut.fabric import AddressRoute  # noqa: E402
from protocol_model.visualization import (  # noqa: E402
    LaneDisplayPolicy,
    VisualizationPublisher,
    project_virtual_dut,
    system_trace_dot,
    virtual_dut_structure_dot,
)


DEMO_NAME = "axi-ahb-apb-chain"
SYSTEM_NAME = "axi_ahb_apb_peripherals"


def _topology_dot() -> str:
    """One arranged overview for this fixed bridge-chain story."""

    return r'''digraph bridge_chain_topology {
  rankdir=TB;
  label="AXI4-Lite → AHB-Lite → APB4 peripheral network";
  labelloc="t";
  graph [bgcolor="white", pad=0.25, nodesep=0.48, ranksep=0.75,
         splines=polyline, ordering=out];
  node [fontname="sans-serif", fontsize=10, shape=box,
        style="rounded,filled", margin="0.14,0.09"];
  edge [fontname="sans-serif", fontsize=9, color="#52606d",
        penwidth=1.35];

  initiator [label="initiator\nVirtualDut · AXI4-Lite manager boundary", fillcolor="#eff6ff", color="#2563eb"];
  axi_ahb [label="axi_to_ahb\nBridge VirtualDut", fillcolor="#fff7ed", color="#ea580c"];
  ahb_apb [label="ahb_to_apb\nBridge VirtualDut", fillcolor="#fff7ed", color="#ea580c"];
  fabric [label="apb_fabric\nVirtualDut · decode · response mux", fillcolor="#fdf2f8", color="#db2777"];

  control [label="control\nVirtualDut · register endpoint", fillcolor="#ecfdf5", color="#059669", group="control"];
  status [label="status\nVirtualDut · register endpoint", fillcolor="#ecfdf5", color="#059669", group="status"];

  { rank=same; initiator; axi_ahb; ahb_apb; }

  initiator -> axi_ahb [dir=none, label=<<B>AXI4-Lite</B><BR/><FONT POINT-SIZE="8">axi_link · initiator.axi ↔ axi_to_ahb.s_axi</FONT>>];
  axi_ahb -> ahb_apb [dir=none, label=<<B>AHB-Lite</B><BR/><FONT POINT-SIZE="8">ahb_link · axi_to_ahb.m_ahb ↔ ahb_to_apb.s_ahb</FONT>>];
  ahb_apb -> fabric [dir=none, label=<<B>APB4</B><BR/><FONT POINT-SIZE="8">apb_upstream · ahb_to_apb.m_apb ↔ apb_fabric.upstream</FONT>>];
  fabric -> control [dir=none, label=<<B>APB4</B><BR/><FONT POINT-SIZE="8">apb_control · apb_fabric.control ↔ control.apb</FONT>>];
  fabric -> status [dir=none, label=<<B>APB4</B><BR/><FONT POINT-SIZE="8">apb_status · apb_fabric.status ↔ status.apb</FONT>>];
  { rank=same; control; status; }
  control -> status [style=invis, weight=80];
}
'''


def _expanded_topology_dot() -> str:
    """Hand-arranged expanded view for this one publication."""

    return r'''digraph bridge_chain_expanded {
  rankdir=TB;
  label="AXI4-Lite → AHB-Lite → APB4 · attached VirtualDut realization";
  labelloc="t";
  graph [bgcolor="white", pad=0.28, nodesep=0.38, ranksep=0.62,
         splines=polyline, ordering=out];
  node [fontname="sans-serif", fontsize=10];
  edge [fontname="sans-serif", fontsize=9, color="#52606d", penwidth=1.3];

  scenario [shape=note, style="rounded,dashed,filled", fillcolor="#fff7ed",
            color="#ea580c", label="scenario-owned actions\noutside VirtualDut"];

  initiator [shape=plain, label=<
    <TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="6" COLOR="#2563eb">
      <TR><TD BGCOLOR="#eff6ff"><B>initiator · VirtualDut</B></TD></TR>
      <TR><TD PORT="axi" BGCOLOR="#dbeafe">AXI4-Lite manager port</TD></TR>
      <TR><TD BGCOLOR="#ecfdf5">capture returned B / R events</TD></TR>
    </TABLE>>];

  axi_ahb [shape=plain, label=<
    <TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="6" COLOR="#ea580c">
      <TR><TD BGCOLOR="#fff7ed"><B>axi_to_ahb · Bridge VirtualDut</B><BR/><FONT POINT-SIZE="9">request flows downward · completion folds upward</FONT></TD></TR>
      <TR><TD PORT="s_axi" BGCOLOR="#e0f2fe">s_axi port + AXI4-Lite completer attachment</TD></TR>
      <TR><TD BGCOLOR="#ecfeff">AddressAccess operation adapter</TD></TR>
      <TR><TD BGCOLOR="#fdf4ff">decode protection → route → target shape → encode</TD></TR>
      <TR><TD BGCOLOR="#f5f3ff">serial child scheduler · capacity 8 · one child active</TD></TR>
      <TR><TD BGCOLOR="#fff7ed">child owner table · child completion → parent completion</TD></TR>
      <TR><TD PORT="m_ahb" BGCOLOR="#e0f2fe">m_ahb port + AHB requester attachment</TD></TR>
    </TABLE>>];

  ahb_apb [shape=plain, label=<
    <TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="6" COLOR="#ea580c">
      <TR><TD BGCOLOR="#fff7ed"><B>ahb_to_apb · Bridge VirtualDut</B><BR/><FONT POINT-SIZE="9">request flows downward · completion folds upward</FONT></TD></TR>
      <TR><TD PORT="s_ahb" BGCOLOR="#e0f2fe">s_ahb port + AHB completer attachment</TD></TR>
      <TR><TD BGCOLOR="#ecfeff">AddressAccess operation adapter</TD></TR>
      <TR><TD BGCOLOR="#fdf4ff">decode protection → route → target shape → encode</TD></TR>
      <TR><TD BGCOLOR="#f5f3ff">serial child scheduler · capacity 8 · one child active</TD></TR>
      <TR><TD BGCOLOR="#fff7ed">child owner table · child completion → parent completion</TD></TR>
      <TR><TD PORT="m_apb" BGCOLOR="#e0f2fe">m_apb port + APB requester attachment</TD></TR>
    </TABLE>>];

  fabric [shape=plain, label=<
    <TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="6" COLOR="#db2777">
      <TR><TD BGCOLOR="#fdf2f8" COLSPAN="2"><B>apb_fabric · VirtualDut</B></TD></TR>
      <TR><TD PORT="up" BGCOLOR="#e0f2fe" COLSPAN="2">upstream port + APB completer attachment</TD></TR>
      <TR><TD BGCOLOR="#fdf2f8" COLSPAN="2">address decoder · 0x1000 control / 0x2000 status</TD></TR>
      <TR><TD BGCOLOR="#fff7ed" COLSPAN="2">pending owner + response mux</TD></TR>
      <TR><TD PORT="control" BGCOLOR="#e0f2fe">control requester attachment</TD><TD PORT="status" BGCOLOR="#e0f2fe">status requester attachment</TD></TR>
    </TABLE>>];

  control [shape=box, style="rounded,filled", fillcolor="#ecfdf5", color="#059669",
           label="control · VirtualDut\nAPB attachment + register region", group="control"];
  status [shape=box, style="rounded,filled", fillcolor="#ecfdf5", color="#059669",
          label="status · VirtualDut\nAPB attachment + register region", group="status"];

  { rank=same; scenario; initiator; axi_ahb; ahb_apb; }
  { rank=same; control; status; }

  scenario -> initiator [style=dashed, color="#ea580c", label="drive / observe"];
  initiator:axi -> axi_ahb:s_axi [dir=none, label=<<B>AXI4-Lite</B><BR/><FONT POINT-SIZE="8">axi_link · initiator.axi ↔ axi_to_ahb.s_axi</FONT>>];
  axi_ahb:m_ahb -> ahb_apb:s_ahb [dir=none, label=<<B>AHB-Lite</B><BR/><FONT POINT-SIZE="8">ahb_link · axi_to_ahb.m_ahb ↔ ahb_to_apb.s_ahb</FONT>>];
  ahb_apb:m_apb -> fabric:up [dir=none, label=<<B>APB4</B><BR/><FONT POINT-SIZE="8">apb_upstream · ahb_to_apb.m_apb ↔ apb_fabric.upstream</FONT>>];
  fabric:control -> control [dir=none, label=<<B>APB4</B><BR/><FONT POINT-SIZE="8">apb_control · apb_fabric.control ↔ control.apb</FONT>>];
  fabric:status -> status [dir=none, label=<<B>APB4</B><BR/><FONT POINT-SIZE="8">apb_status · apb_fabric.status ↔ status.apb</FONT>>];
  control -> status [style=invis, weight=80];
}
'''


def _vertical_layout(dot: str) -> str:
    return dot.replace("  rankdir=LR;", "  rankdir=TB;", 1)


def _two_column_trace(dot: str) -> str:
    return dot.replace(
        "splines=polyline];",
        'splines=polyline, pack=true, packmode="array_u2"];',
        1,
    )


def _build_system():
    """Return the executable system and its three concrete link protocols."""

    axi = build_axi4_lite_interface()
    ahb = build_ahb_lite_interface()
    apb = build_apb4_interface()

    # Request choice remains scenario-owned.  This module boundary only
    # declares the AXI role and captures B/R events returned by the network.
    initiator = VirtualDut(
        "initiator",
        {"axi": InterfacePort("axi", axi, "manager")},
        backend=CaptureBackend(),
        description="externally driven AXI4-Lite requester boundary",
    )
    axi_to_ahb = build_amba_serial_bridge_vdut(
        "axi_to_ahb",
        axi,
        ahb,
        (AddressRoute("peripheral_window", 0x1000, 0x3000, "m_ahb"),),
        ingress_port="s_axi",
        egress_port="m_ahb",
    )
    ahb_to_apb = build_amba_serial_bridge_vdut(
        "ahb_to_apb",
        ahb,
        apb,
        (AddressRoute("peripheral_window", 0x1000, 0x3000, "m_apb"),),
        ingress_port="s_ahb",
        egress_port="m_apb",
    )
    fabric = build_apb_address_fabric_vdut(
        "apb_fabric",
        apb,
        (
            AddressRoute("control", 0x1000, 0x100, "control"),
            AddressRoute("status", 0x2000, 0x100, "status"),
        ),
    )
    control = build_apb_address_space_vdut(
        "control",
        apb,
        AddressSpace(
            (
                RegisterRegion(
                    "control_registers",
                    (RegisterSpec("value", 0),),
                    base_address=0x1000,
                ),
            )
        ),
    )
    status = build_apb_address_space_vdut(
        "status",
        apb,
        AddressSpace(
            (
                RegisterRegion(
                    "status_registers",
                    (RegisterSpec("value", 0),),
                    base_address=0x2000,
                ),
            )
        ),
    )

    links = (
        InterfaceConnection(
            "axi_link",
            axi,
            {
                "manager": VirtualDutPortRef("initiator", "axi"),
                "subordinate": VirtualDutPortRef("axi_to_ahb", "s_axi"),
            },
        ),
        InterfaceConnection(
            "ahb_link",
            ahb,
            {
                "manager": VirtualDutPortRef("axi_to_ahb", "m_ahb"),
                "subordinate": VirtualDutPortRef("ahb_to_apb", "s_ahb"),
            },
        ),
        InterfaceConnection(
            "apb_upstream",
            apb,
            {
                "requester": VirtualDutPortRef("ahb_to_apb", "m_apb"),
                "completer": VirtualDutPortRef("apb_fabric", "upstream"),
            },
        ),
        InterfaceConnection(
            "apb_control",
            apb,
            {
                "requester": VirtualDutPortRef("apb_fabric", "control"),
                "completer": VirtualDutPortRef("control", "apb"),
            },
        ),
        InterfaceConnection(
            "apb_status",
            apb,
            {
                "requester": VirtualDutPortRef("apb_fabric", "status"),
                "completer": VirtualDutPortRef("status", "apb"),
            },
        ),
    )
    duts = (initiator, axi_to_ahb, ahb_to_apb, fabric, control, status)
    return (
        SystemProtocol(
            SYSTEM_NAME,
            {dut.name: dut for dut in duts},
            {link.name: link for link in links},
        ),
        (axi, ahb, apb),
    )


def _action(kind: str, payload: dict[str, object]) -> SystemAction:
    return SystemAction(
        VirtualDutPortRef("initiator", "axi"),
        CanonicalEvent(kind, None, payload),
    )


def _record(label: str, transition) -> dict[str, object]:
    return {
        "label": label,
        "fault": (
            None
            if transition.fault is None
            else {
                "rule": transition.fault.rule,
                "reason": transition.fault.reason,
            }
        ),
        "emissions": [
            {
                "index": event.index,
                "link": event.connection,
                "event_kind": event.event_kind,
                "source": event.source.qualified_name,
                "destination": event.destination.qualified_name,
                "kind": event.event.kind,
                "payload": dict(event.event.payload),
            }
            for event in transition.emissions
        ],
    }


def _data_lane(name: str, values: list[str | None]) -> dict[str, object]:
    """Encode one model-step lane without implying clock continuity."""

    wave: list[str] = []
    data: list[str] = []
    idle = False
    for value in values:
        if value is None:
            wave.append("." if idle else "x")
            idle = True
        else:
            wave.append("=")
            data.append(value)
            idle = False
    return {"name": name, "wave": "".join(wave), "data": data}


def _event_label(event: dict[str, object]) -> str:
    kind = str(event["kind"])
    payload = dict(event["payload"])
    if kind in {"AW", "AR"}:
        return f"{kind}@{int(payload['addr']):04x}"
    if kind in {"READ", "WRITE"}:
        short = "RD" if kind == "READ" else "WR"
        return f"{short}@{int(payload['addr']):04x}"
    if kind in {"W", "WRITE_DATA"}:
        short = "W" if kind == "W" else "WD"
        return f"{short}={int(payload['data']):08x}"
    if kind == "R":
        return (
            f"R {payload['resp']}={int(payload['data']):08x}"
        )
    if kind == "B":
        return f"B {payload['resp']}"
    if kind == "READ_RESPONSE":
        if "error" in payload:
            status = "ERR" if payload["error"] else "OK"
        else:
            status = str(payload["resp"])
        return f"RR {status}={int(payload['data']):08x}"
    if kind == "WRITE_RESPONSE":
        if "error" in payload:
            status = "ERR" if payload["error"] else "OK"
        else:
            status = str(payload["resp"])
        return f"WR {status}"
    return kind


def _link_lane(
    records: list[dict[str, object]],
    link: str,
    kinds: frozenset[str],
) -> list[str | None]:
    values: list[str | None] = []
    for record in records:
        selected = [
            _event_label(event)
            for event in record["emissions"]
            if event["link"] == link and event["kind"] in kinds
        ]
        values.append(" + ".join(selected) if selected else None)
    return values


def _wavejson(records: list[dict[str, object]]) -> dict[str, object]:
    """Project each scenario action and its causal propagation into lanes."""

    policy = LaneDisplayPolicy(hide_inactive=True)
    lane_specs = (
        (
            "AXI request",
            "axi_link",
            frozenset(("AW", "W", "AR")),
        ),
        (
            "AHB request",
            "ahb_link",
            frozenset(("READ", "WRITE", "WRITE_DATA")),
        ),
        (
            "APB upstream request",
            "apb_upstream",
            frozenset(("READ", "WRITE")),
        ),
        (
            "control endpoint",
            "apb_control",
            frozenset(("READ", "WRITE", "READ_RESPONSE", "WRITE_RESPONSE")),
        ),
        (
            "status endpoint",
            "apb_status",
            frozenset(("READ", "WRITE", "READ_RESPONSE", "WRITE_RESPONSE")),
        ),
        (
            "APB upstream completion",
            "apb_upstream",
            frozenset(("READ_RESPONSE", "WRITE_RESPONSE")),
        ),
        (
            "AHB completion",
            "ahb_link",
            frozenset(("READ_RESPONSE", "WRITE_RESPONSE")),
        ),
        (
            "AXI completion",
            "axi_link",
            frozenset(("B", "R")),
        ),
    )
    lanes: list[dict[str, object]] = []
    for name, link, kinds in lane_specs:
        values = _link_lane(records, link, kinds)
        if policy.shows(name, active=any(value is not None for value in values)):
            lanes.append(_data_lane(name, values))
    return {
        "signal": [
            _data_lane(
                "SCENARIO STEP",
                [
                    "S0 ctrl W data",
                    "S1 ctrl AW",
                    "S2 stat W data",
                    "S3 stat AW",
                    "S4 ctrl AR",
                    "S5 stat AR",
                    "S6 miss AR",
                ],
            ),
            ["request", *lanes[:5]],
            ["return", *lanes[5:]],
        ],
        "head": {
            "text": (
                "AXI4-Lite → AHB-Lite → APB4 transaction propagation / "
                "跨协议事务传播"
            )
        },
        "foot": {
            "text": (
                "1 column = 1 scenario action plus causally triggered events · "
                "MODEL ORDER ONLY · NOT PINS/CYCLES/RTL / 非引脚时序"
            )
        },
        "config": {"hscale": 5},
    }


def _validate_wavejson(wavejson: dict[str, object], expected_steps: int) -> None:
    signal = wavejson.get("signal")
    if not isinstance(signal, list) or not signal:
        raise RuntimeError("waveform projection has no signal lanes")
    step_lane = signal[0]
    if not isinstance(step_lane, dict) or len(step_lane.get("wave", "")) != expected_steps:
        raise RuntimeError("waveform does not cover every scenario step")


def _read_response(transition) -> tuple[str, int]:
    response = transition.emissions[-1].event
    if response.kind != "R":
        raise RuntimeError(f"expected AXI4-Lite R, observed {response.kind}")
    return str(response.payload["resp"]), int(response.payload["data"])


def _execute(system: SystemProtocol):
    session = system.open_session()
    state = session.initial_state()
    records: list[dict[str, object]] = []

    def apply(label: str, kind: str, payload: dict[str, object]):
        nonlocal state
        transition = session.step(state, _action(kind, payload))
        if transition.fault is not None:
            raise RuntimeError(
                f"{label} faulted: {transition.fault.rule}: "
                f"{transition.fault.reason}"
            )
        state = transition.state
        records.append(_record(label, transition))
        return transition

    # AXI4-Lite permits AW and W to arrive independently.  Sending W first
    # makes the join state visible before the completed write enters AHB.
    apply("control write data", "W", {"data": 0x11223344, "strb": 0xF})
    control_write = apply(
        "control write address", "AW", {"addr": 0x1000, "prot": 0}
    )
    apply("status write data", "W", {"data": 0xAABBCCDD, "strb": 0xF})
    status_write = apply(
        "status write address", "AW", {"addr": 0x2000, "prot": 0}
    )
    control_read = apply(
        "control read", "AR", {"addr": 0x1000, "prot": 0}
    )
    status_read = apply(
        "status read", "AR", {"addr": 0x2000, "prot": 0}
    )
    decode_miss = apply(
        "unmapped read", "AR", {"addr": 0x3000, "prot": 0}
    )

    for transition in (control_write, status_write):
        response = transition.emissions[-1].event
        if response.kind != "B" or response.payload["resp"] != "OKAY":
            raise RuntimeError("write did not return an AXI4-Lite OKAY response")
    control_resp, control_data = _read_response(control_read)
    status_resp, status_data = _read_response(status_read)
    miss_resp, _ = _read_response(decode_miss)
    if (control_resp, control_data) != ("OKAY", 0x11223344):
        raise RuntimeError("control endpoint readback mismatch")
    if (status_resp, status_data) != ("OKAY", 0xAABBCCDD):
        raise RuntimeError("status endpoint readback mismatch")
    if miss_resp != "SLVERR":
        raise RuntimeError("APB decode miss did not return AXI4-Lite SLVERR")
    if not session.is_quiescent(state):
        raise RuntimeError("bridge chain did not return to quiescence")

    return session, state, records


def _readme() -> str:
    return """# AXI4-Lite → AHB-Lite → APB4 execution

The current architecture executed a deterministic write/read pair against two
APB endpoints through two independently constructed bridges.

![Compact topology](topology.svg)

The compact view is the primary network map.  It keeps one box per concrete
module and makes the three protocol families and two APB endpoint links easy
to follow.

Each connection is drawn directly between VirtualDuts. Its bold label is the
InterfaceProtocol name; the smaller label identifies the concrete InterfaceConnection and
the two bound ports. No additional diamond-shaped hardware node is implied.

## Expanded, inspectable realization

![Expanded topology](expanded-topology.svg)

The orange dashed note is scenario-owned.  `initiator` only provides the
AXI4-Lite manager boundary and captures returned responses. The expanded view
keeps each bridge/fabric interface port and attachment at the module boundary;
the separate structure figures below use the shared VirtualDut projector for
the complete constructed internals.

## Cross-interface transaction view

![WaveDrom transaction view](waveform.svg)

Each column starts with one scenario action and includes the protocol events
causally triggered during that `SystemSession.step`.  It is a model-order
projection, not AXI/AHB/APB pins, cycles, or RTL timing.

## Bridge realizations

![AXI4-Lite to AHB-Lite bridge](axi-to-ahb-structure.svg)

![AHB-Lite to APB4 bridge](ahb-to-apb-structure.svg)

Each bridge has two protocol attachments around a typed translation plan, a
serial child scheduler, and completion ownership.  The second bridge receives
the AHB WRITE and WRITE_DATA events, joins them into one address operation,
and emits one APB transfer.

## APB routing realization

![APB decoder and response mux](apb-fabric-structure.svg)

The APB fabric selects `control` or `status`, holds the selected egress owner,
and returns the endpoint completion through the upstream APB link.

The unmapped `0x3000` read reaches this decoder but no endpoint link.  APB's
single error bit returns through AHB `ERROR` as AXI4-Lite `SLVERR`; it cannot
retain AXI's finer `DECERR`/`SLVERR` distinction.  This is an observed protocol
projection boundary rather than a hidden bridge failure.

## Causal execution

![Causal trace](causality.svg)

The complete machine-readable execution is in [result.json](result.json).
The publication retains every [DOT source](sources/), its
[provenance](provenance.json), and [manifest](manifest.json).

This is a transaction-semantic network.  It demonstrates composition and
return-path ownership; it does not claim pin/cycle timing, arbitration,
multiple initiators, or coherence behavior.
"""


def _require_renderer() -> None:
    if shutil.which("dot") is None:
        raise SystemExit("Missing renderer dependency: Graphviz 'dot'")


def _build_publication(directory: Path) -> Path:
    system, protocols = _build_system()
    session, state, records = _execute(system)
    store = RunArtifactStore("vdut-axi-ahb-apb-chain", directory)
    publisher = VisualizationPublisher(store)

    wavejson = _wavejson(records)
    _validate_wavejson(wavejson, len(records))
    publisher.render_wave("waveform", wavejson, kind="waveform")

    publisher.render_dot(
        "topology",
        _topology_dot(),
        kind="topology",
    )
    publisher.render_dot(
        "expanded-topology",
        _expanded_topology_dot(),
        kind="topology",
    )
    for dut_name, artifact_name in (
        ("axi_to_ahb", "axi-to-ahb-structure"),
        ("ahb_to_apb", "ahb-to-apb-structure"),
        ("apb_fabric", "apb-fabric-structure"),
    ):
        dut = system.virtual_duts[dut_name]
        publisher.render_dot(
            artifact_name,
            _vertical_layout(
                virtual_dut_structure_dot(project_virtual_dut(dut))
            ),
            kind="vdut_structure",
        )
    publisher.render_dot(
        "causality",
        _two_column_trace(
            system_trace_dot(
                session.trace(state),
                title="AXI4-Lite → AHB-Lite → APB4 causal execution",
            )
        ),
        kind="causality",
    )

    store.write_json(
        "result.json",
        {
            "schema": "protocol-model.showcase.amba-bridge-chain/v1",
            "system": {
                "name": system.name,
                "virtual_duts": list(system.virtual_duts),
                "links": list(system.connections),
            },
            "steps": records,
            "assertions": {
                "fault_free": True,
                "control_readback": "0x11223344",
                "status_readback": "0xaabbccdd",
                "unmapped_read": "SLVERR after APB error-bit projection",
                "final_quiescent": True,
            },
            "event_count": len(state.events),
            "causal_edges": [list(edge) for edge in state.causal_edges],
        },
        kind="execution_result",
    )
    store.write_text(
        "README.md",
        _readme(),
        kind="demo_guide",
        media_type="text/markdown",
    )
    store.write_json(
        "provenance.json",
        {
            "schema": "protocol-model.showcase.provenance/v1",
            "demo": DEMO_NAME,
            "source": "showcase/demos/vdut/axi_ahb_apb_chain/run.py",
            "command": (
                "python3 showcase/demos/vdut/axi_ahb_apb_chain/run.py"
            ),
            "protocol_model_version": __version__,
            "execution_models": [
                "SystemSession",
                "AddressOperationTranslationBridgeBackend",
                "SingleIngressAddressFabricBackend",
                "PassiveAddressSpaceBackend",
            ],
            "renderers": {
                "waveform": "WaveDrom 3.6.2 + shared visualization publisher",
                "topology": "Graphviz dot + demo-local arranged overview",
                "expanded_topology": (
                    "Graphviz dot + one-off hand-arranged expanded view"
                ),
                "vdut_structure": (
                    "Graphviz dot + shared projection, vertical arrangement"
                ),
                "causality": (
                    "Graphviz dot + shared trace, hand-arranged in two columns"
                ),
            },
            "presentation_boundary": (
                "canonical event/operation composition; not AMBA pin cycles, "
                "RTL, arbitration, or coherence"
            ),
        },
        kind="provenance",
    )
    return store.finalize(
        verdict="PASS",
        protocols=(
            protocol_record_from_system(system),
            *(protocol_record_from_interface(protocol) for protocol in protocols),
        ),
        cases=(
            {
                "name": "two-endpoint-write-read-and-decode-miss",
                "expected": (
                    "two equal readbacks, SLVERR for APB decode miss, "
                    "final quiescence"
                ),
                "observed": "PASS",
            },
        ),
        state={
            "event_count": len(state.events),
            "causal_edge_count": len(state.causal_edges),
            "final_quiescent": True,
        },
        metadata={
            "publication": "showcase/generated/vdut/axi-ahb-apb-chain",
            "network_scope": "non-coherent single-initiator address network",
            "raw_pin_capture": False,
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
        description="Publish the AXI4-Lite/AHB-Lite/APB4 chain demo."
    )
    parser.add_argument(
        "--publish-root",
        type=Path,
        default=SHOWCASE_ROOT / "generated" / "vdut",
        help="parent directory of the stable demo publication",
    )
    args = parser.parse_args(argv)
    publish_root = args.publish_root.expanduser().resolve()
    target = publish_root / DEMO_NAME
    build_root = publish_root.parent / ".build"
    build_root.mkdir(parents=True, exist_ok=True)

    _require_renderer()
    with TemporaryDirectory(prefix=f"{DEMO_NAME}-", dir=build_root) as temporary:
        staged = Path(temporary) / DEMO_NAME
        manifest = _build_publication(staged)
        if not manifest.is_file():
            raise RuntimeError("staged demo has no manifest")
        for required in (
            "README.md",
            "result.json",
            "waveform.svg",
            "sources/waveform.json",
            "topology.svg",
            "expanded-topology.svg",
            "axi-to-ahb-structure.svg",
            "ahb-to-apb-structure.svg",
            "apb-fabric-structure.svg",
            "causality.svg",
            "provenance.json",
        ):
            if not (staged / required).is_file():
                raise RuntimeError(f"staged demo lacks {required}")
        _publish(staged, target)

    try:
        build_root.rmdir()
    except OSError:
        pass
    print(f"Published AMBA bridge-chain demo: {target}")
    print(f"Manifest: {target / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
