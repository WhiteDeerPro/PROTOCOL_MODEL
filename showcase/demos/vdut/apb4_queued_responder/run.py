#!/usr/bin/env python3
"""Execute and publish an APB4 random-source + queued-responder demo.

Run from any working directory with Python 3.10 or newer:

    python3 showcase/demos/vdut/apb4_queued_responder/run.py

The publication is deliberately explicit.  The source and target are concrete
VirtualDut module boundaries, APB4 supplies their shared link semantics, the
target attachment lowers requests into AddressAccess values, and the backend
only progresses when the scenario sends DutAdvanceAction.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from random import Random
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
from protocol_model.integrations.recipes.amba.endpoints.queued import (  # noqa: E402
    build_amba_queued_address_responder_vdut,
)
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface  # noqa: E402
from protocol_model.scenario import assemble_random_traffic_source  # noqa: E402
from protocol_model.semantics import EventOffer  # noqa: E402
from protocol_model.system import (  # noqa: E402
    DutAdvanceAction,
    SystemProtocol,
)
from protocol_model.virtual_dut.address import (  # noqa: E402
    AddressRead,
    AddressSpace,
    AddressWrite,
    MemoryRegion,
)
from protocol_model.virtual_dut.backend.queued_address import (  # noqa: E402
    QueuedAddressResponderBackend,
    QueuedAddressResponderState,
)
from protocol_model.visualization import (  # noqa: E402
    VisualizationPublisher,
    project_virtual_dut,
    system_trace_dot,
    virtual_dut_structure_dot,
)


DEMO_NAME = "apb4-queued-responder"
SEED = 20260717
TARGET_NAME = "queued_memory"
LINK_NAME = "apb4_bus"
ADDRESS = 0x1004


def _quoted(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _bool_wave(values: list[bool]) -> str:
    previous: bool | None = None
    result = []
    for value in values:
        result.append("." if value is previous else ("1" if value else "0"))
        previous = value
    return "".join(result)


def _data_lane(name: str, values: list[object | None]) -> dict[str, object]:
    wave: list[str] = []
    data: list[str] = []
    idle = False
    for value in values:
        if value is None:
            wave.append("." if idle else "x")
            idle = True
        else:
            wave.append("=")
            data.append(str(value))
            idle = False
    return {"name": name, "wave": "".join(wave), "data": data}


def _event_label(kind: str, payload: dict[str, object]) -> str:
    if kind == "WRITE":
        return (
            f"W A={int(payload['addr']):x} "
            f"D={int(payload['data']):08x} "
            f"S={int(payload['strb']):x}"
        )
    if kind == "READ":
        return f"R A={int(payload['addr']):x}"
    if kind == "READ_RESPONSE":
        return (
            f"R_RESP D={int(payload['data']):08x} "
            f"{'ERR' if payload['error'] else 'OK'}"
        )
    if kind == "WRITE_RESPONSE":
        return f"W_RESP {'ERR' if payload['error'] else 'OK'}"
    return kind


def _target_snapshot(system_session, state) -> dict[str, object]:
    target_state = state.dut_states[TARGET_NAME]
    if not isinstance(target_state, QueuedAddressResponderState):
        raise TypeError("demo target does not expose queued responder state")
    head = target_state.queue[0] if target_state.queue else None
    return {
        "fifo_occupancy": len(target_state.queue),
        "fifo_capacity": 2,
        "head_phase": head.phase.value if head is not None else "empty",
        "head_remaining_delay": (
            head.remaining_delay_steps if head is not None else None
        ),
        "advance_index": target_state.advance_index,
        "quiescent": system_session.is_quiescent(state),
    }


def _step_record(label: str, action: str, transition, session) -> dict[str, object]:
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
        "emissions": [
            {
                "index": item.index,
                "link": item.connection,
                "event_kind": item.event_kind,
                "source": item.source.qualified_name,
                "destination": item.destination.qualified_name,
                "event": {
                    "kind": item.event.kind,
                    "payload": dict(item.event.payload),
                    "trace_index": item.event.trace_index,
                },
            }
            for item in transition.emissions
        ],
        "target": _target_snapshot(session, transition.state),
    }


def _wavejson(steps: list[dict[str, object]]) -> dict[str, object]:
    requests: list[str | None] = []
    responses: list[str | None] = []
    service: list[bool] = []
    phase_transitions: list[str] = []
    for step in steps:
        emitted = step["emissions"]
        request = None
        response = None
        for located in emitted:
            event = located["event"]
            kind = event["kind"]
            payload = event["payload"]
            label = _event_label(kind, payload)
            if kind in {"READ", "WRITE"}:
                request = label
            else:
                response = label
        requests.append(request)
        responses.append(response)
        service.append(response is not None)
        target = step["target"]
        if response is not None:
            phase_transitions.append("READY → service")
        elif target["fifo_occupancy"] == 0:
            phase_transitions.append("idle")
        elif str(step["action"]).startswith("generate"):
            phase_transitions.append(
                f"enqueue {str(target['head_phase']).upper()}"
                f"({target['head_remaining_delay']})"
            )
        else:
            phase_transitions.append(
                f"age → {str(target['head_phase']).upper()}"
                f"({target['head_remaining_delay']})"
            )

    targets = [step["target"] for step in steps]
    return {
        "signal": [
            _data_lane("MODEL STEP", [step["label"] for step in steps]),
            [
                "Scenario",
                _data_lane("action", [step["action"] for step in steps]),
                {
                    "name": "DutAdvanceAction",
                    "wave": _bool_wave(
                        [str(step["action"]).startswith("advance") for step in steps]
                    ),
                },
            ],
            [
                "APB4 event link",
                _data_lane("requester → completer", requests),
                _data_lane("completer → requester", responses),
            ],
            [
                "Target VirtualDut",
                _data_lane(
                    "FIFO occupancy",
                    [
                        f"{target['fifo_occupancy']}/{target['fifo_capacity']}"
                        for target in targets
                    ],
                ),
                _data_lane("phase transition", phase_transitions),
                _data_lane(
                    "head post-state",
                    [
                        (
                            target["head_phase"]
                            if target["head_remaining_delay"] is None
                            else (
                                f"{target['head_phase']} "
                                f"({target['head_remaining_delay']} left)"
                            )
                        )
                        for target in targets
                    ],
                ),
                {"name": "handler service", "wave": _bool_wave(service)},
                {
                    "name": "system quiescent",
                    "wave": _bool_wave(
                        [bool(target["quiescent"]) for target in targets]
                    ),
                },
            ],
        ],
        "head": {
            "text": "APB4 random source → queued VirtualDut / 随机源到排队式虚拟模块"
        },
        "foot": {
            "text": (
                "Event/service-step projection · not PSEL/PENABLE, cycles, RTL or VCD / "
                "事件与服务步投影，并非引脚时序"
            )
        },
        "config": {"hscale": 5},
    }


def _topology_dot(protocol, write_delay: int, read_delay: int) -> str:
    return f'''digraph apb4_queued_demo {{
  rankdir=TB;
  label="APB4 integrated VirtualDut demo / APB4 集成后虚拟模块实例";
  labelloc="t";
  graph [bgcolor="white", pad=0.3, nodesep=0.48, ranksep=0.55, splines=polyline, compound=true];
  node [shape=box, style="rounded,filled", fontname="sans-serif", margin="0.15,0.10"];
  edge [fontname="sans-serif", fontsize=9, color="#456579"];

  controller [label="Scenario-owned random controller\\nseed {SEED} · protocol-valid offers\\n场景拥有，不是 DUT 内部随机状态", fillcolor="#f5efff", color="#7356a8"];

  subgraph cluster_source {{
    label="random_source VirtualDut";
    color="#8ab2d1";
    style="rounded";
    source_backend [label="NoOp backend\\nconcrete module boundary", fillcolor="#eef5ff", color="#3169a8"];
    source_attachment [label="EmptyEndpointAttachment\\nmode: idle_source\\nno autonomous APB emission", fillcolor="#e0f2fe", color="#0284c7"];
    source_port [label="apb interface port\\nAPB4 · requester", fillcolor="#dbeafe", color="#2563eb"];
    {{ rank=same; source_backend; source_attachment; source_port; }}
    source_backend -> source_attachment [style=dotted, label="no autonomous emission"];
    source_attachment -> source_port [label="declared output"];
  }}

  subgraph cluster_target {{
    label="queued_memory VirtualDut · integration recipe result";
    color="#d29752";
    style="rounded";
    target_port [label="apb interface port\\nAPB4 · completer", fillcolor="#dbeafe", color="#2563eb"];
    attachment [label="ApbCompleterAttachment\\nAPB4 event ↔ AddressAccess", fillcolor="#fff4e7", color="#b56b21"];
    fifo [label="QueuedAddressResponderBackend\\nFIFO capacity 2\\nDELAYING → READY → service", fillcolor="#fff8dc", color="#a17a1c"];
    delay [label="dynamic delay policy\\nWRITE={write_delay} · READ={read_delay} advances", fillcolor="#fff8dc", color="#a17a1c"];
    handler [label="AddressSpace handler\\nMemoryRegion 0x1000..0x10ff", fillcolor="#f0f7ed", color="#4f8243"];
    {{ rank=same; attachment; fifo; }}
    {{ rank=same; delay; handler; }}
    target_port -> attachment -> fifo -> delay -> handler;
  }}

  scheduler [label="explicit service boundary\\nDutAdvanceAction(queued_memory)", fillcolor="#f4f5f6", color="#6f7d86"];
  controller -> source_port [style=dashed, label="drives protocol-valid offer"];
  source_port -> target_port [dir=none, penwidth=1.7, label=<<B>AMBA APB4</B><BR/><FONT POINT-SIZE="8">apb4_bus · random_source.apb ↔ queued_memory.apb</FONT>>];
  scheduler -> fifo [style=dashed, label="advance", lhead=cluster_target];
}}
'''


def _readme(write_data: int) -> str:
    return f"""# APB4 queued-responder execution

This publication was produced by the current model, not hand-drawn from an
expected result.

![Connection structure](topology.svg)

The topology distinguishes two constructions that are easy to conflate:

- `queued_memory` is a concrete `VirtualDut` returned by an AMBA integration
  recipe. Its APB4 attachment, finite FIFO, delay policy and address handler
  are module-local behavior.
- `random_source` is a concrete idle source `VirtualDut`, while the seeded
  traffic controller belongs to the scenario and drives its port from outside.
  Its EmptyEndpointAttachment records that the module has no autonomous APB
  emission; the scenario controller is deliberately kept outside that boundary.

Together with `apb4_bus`, they form one executable AMBA APB4 model instance.
The APB4-labeled edge is that concrete InterfaceConnection; its smaller line names the
link instance and the two bound module ports. It is a connection, not an extra
hardware node.

The instance models normalized transaction semantics. It is not an RTL module
instance and does not claim to emit PSEL/PENABLE cycles.

## WaveDrom execution view

![WaveDrom execution view](waveform.svg)

The controller generated a full-strobe write to `0x{ADDRESS:x}` with random
data `0x{write_data:08x}`, followed by a read of the same address. The target
used a dynamic policy: writes wait two explicit service advances and reads
wait one. FIFO occupancy and completion therefore come from the executed
VirtualDut state.

## Target VirtualDut realization

![Target VirtualDut realization](target-structure.svg)

This view comes from the reusable VirtualDut structure projector. It treats
the module boundary as the outer box and keeps the APB attachment, request
FIFO, delay/service controller and AddressSpace as separate constructed
components. An unknown external backend would remain one opaque node.

## Causal trace

![Causal trace](causality.svg)

Machine-readable evidence: [result.json](result.json),
[WaveJSON](sources/waveform.json), [topology DOT](sources/topology.dot),
[VirtualDut structure DOT](sources/target-structure.dot),
[causality DOT](sources/causality.dot), and
[provenance.json](provenance.json).
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
    protocol = build_apb4_interface()
    source = assemble_random_traffic_source(
        "random_source",
        protocol,
        "requester",
        Random(SEED),
        port_name="apb",
        connection_name=LINK_NAME,
    )

    def dynamic_delay(access, _context) -> int:
        if isinstance(access, AddressWrite):
            return 2
        if isinstance(access, AddressRead):
            return 1
        raise TypeError(f"unsupported access {type(access).__name__}")

    target = build_amba_queued_address_responder_vdut(
        TARGET_NAME,
        protocol,
        AddressSpace(
            (
                MemoryRegion(
                    "ram",
                    0x100,
                    base_address=0x1000,
                    initial_content=bytes(0x100),
                ),
            )
        ),
        capacity=2,
        delay_policy=dynamic_delay,
        port_name="apb",
    )
    if not isinstance(target.backend, QueuedAddressResponderBackend):
        raise TypeError("integration recipe did not produce a queued backend")

    system = SystemProtocol.from_interface(
        "apb4_random_to_queued_memory",
        connection_name=LINK_NAME,
        protocol=protocol,
        endpoints={
            "requester": (source.virtual_dut, "apb"),
            "completer": (target, "apb"),
        },
    )
    session = system.open_session()
    target_structure = project_virtual_dut(target)
    state = session.initial_state()
    steps: list[dict[str, object]] = [
        {
            "label": "S0 initial",
            "action": "none",
            "fault": None,
            "emissions": [],
            "target": _target_snapshot(session, state),
        }
    ]

    write = source.controller.drive(
        session,
        state,
        offer=EventOffer.constrained(
            "WRITE",
            payload={"addr": ADDRESS, "strb": 0xF},
        ),
    )
    state = write.transition.state
    steps.append(_step_record("S1 random WRITE", "generate WRITE", write.transition, session))
    write_data = int(write.action.event.payload["data"])

    first_wait = session.step(state, DutAdvanceAction(TARGET_NAME))
    state = first_wait.state
    source.controller.observe_system_events(first_wait.emissions)
    steps.append(_step_record("S2 write waits", "advance #1", first_wait, session))

    write_done = session.step(state, DutAdvanceAction(TARGET_NAME))
    state = write_done.state
    source.controller.observe_system_events(write_done.emissions)
    steps.append(_step_record("S3 write completes", "advance #2", write_done, session))

    read = source.controller.drive(
        session,
        state,
        offer=EventOffer.constrained("READ", payload={"addr": ADDRESS}),
    )
    state = read.transition.state
    steps.append(_step_record("S4 random READ", "generate READ", read.transition, session))

    read_done = session.step(state, DutAdvanceAction(TARGET_NAME))
    state = read_done.state
    source.controller.observe_system_events(read_done.emissions)
    steps.append(_step_record("S5 read completes", "advance #3", read_done, session))

    transitions = (
        write.transition,
        first_wait,
        write_done,
        read.transition,
        read_done,
    )
    faults = [item.fault for item in transitions if item.fault is not None]
    read_responses = [
        item.event
        for item in read_done.emissions
        if item.event.kind == "READ_RESPONSE"
    ]
    if faults:
        raise RuntimeError(f"demo execution faulted: {faults[0].rule}")
    if len(read_responses) != 1:
        raise RuntimeError("demo did not produce one read response")
    read_data = int(read_responses[0].payload["data"])
    if read_data != write_data:
        raise RuntimeError(
            f"readback 0x{read_data:x} differs from write 0x{write_data:x}"
        )
    if not session.is_quiescent(state) or not source.controller.is_quiescent():
        raise RuntimeError("demo did not return to quiescence")

    store = RunArtifactStore("vdut-apb4-queued-responder", directory)
    publisher = VisualizationPublisher(store)
    publisher.render_wave("waveform", _wavejson(steps), kind="waveform")
    publisher.render_dot(
        "topology",
        _topology_dot(protocol, 2, 1),
        kind="topology",
    )
    publisher.render_dot(
        "target-structure",
        virtual_dut_structure_dot(target_structure),
        kind="vdut_structure",
    )
    publisher.render_dot(
        "causality",
        system_trace_dot(
            session.trace(state),
            title="APB4 queued VirtualDut causal trace / 因果轨迹",
        ),
        kind="causality",
    )
    store.write_json(
        "result.json",
        {
            "schema": "protocol-model.showcase.vdut-apb4-queued/v1",
            "seed": SEED,
            "system": {
                "name": system.name,
                "virtual_duts": sorted(system.virtual_duts),
                "link": LINK_NAME,
                "protocol": protocol.name,
            },
            "integration_result": {
                "virtual_dut": target.name,
                "port": "apb",
                "attachment": "ApbCompleterAttachment",
                "backend": type(target.backend).__name__,
                "realization": target_structure.realization.value,
                "fifo_capacity": target.backend.capacity,
                "handler": "AddressSpace(MemoryRegion)",
                "visible_components": [
                    {
                        "kind": component.kind,
                        "label": component.label,
                    }
                    for component in target_structure.components
                ],
            },
            "steps": steps,
            "assertions": {
                "fault_free": True,
                "readback_matches_random_write": True,
                "random_write_data": write_data,
                "readback_data": read_data,
                "final_quiescent": True,
            },
            "causal_edges": [list(edge) for edge in state.causal_edges],
        },
        kind="execution_result",
    )
    store.write_text(
        "README.md",
        _readme(write_data),
        kind="demo_guide",
        media_type="text/markdown",
    )
    store.write_json(
        "provenance.json",
        {
            "schema": "protocol-model.showcase.provenance/v1",
            "demo": DEMO_NAME,
            "source": "showcase/demos/vdut/apb4_queued_responder/run.py",
            "command": (
                "python3 showcase/demos/vdut/apb4_queued_responder/run.py"
            ),
            "protocol_model_version": __version__,
            "seed": SEED,
            "execution_models": [
                "RandomTrafficController",
                "SystemSession",
                "QueuedAddressResponderBackend",
            ],
            "renderers": {
                "waveform": "WaveDrom 3.6.2 (package.json)",
                "topology": "Graphviz dot",
                "vdut_structure": "Graphviz dot",
                "causality": "Graphviz dot",
            },
            "presentation_boundary": (
                "WaveDrom shows canonical events, explicit service steps and "
                "VirtualDut state; it is not APB pin/cycle or RTL/VCD output"
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
                "name": "random-write-readback-with-dynamic-delay",
                "expected": "fault-free, equal readback, final quiescence",
                "observed": "PASS",
            },
        ),
        state={
            "event_count": len(state.events),
            "causal_edge_count": len(state.causal_edges),
            "final_quiescent": True,
        },
        metadata={
            "publication": (
                "showcase/generated/vdut/apb4-queued-responder"
            ),
            "waveform_interpretation": "event/service-step projection",
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
        description="Publish the APB4 queued-responder VirtualDut demo."
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

    _require_renderers()
    with TemporaryDirectory(prefix=f"{DEMO_NAME}-", dir=build_root) as temporary:
        staged = Path(temporary) / DEMO_NAME
        manifest = _build_publication(staged)
        if not manifest.is_file():
            raise RuntimeError("staged demo has no manifest")
        for required in (
            "README.md",
            "result.json",
            "waveform.svg",
            "topology.svg",
            "target-structure.svg",
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
    print(f"Published APB4 queued VirtualDut demo: {target}")
    print(f"Manifest: {target / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
