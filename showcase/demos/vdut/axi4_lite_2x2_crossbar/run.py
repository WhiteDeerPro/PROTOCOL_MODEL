#!/usr/bin/env python3
"""Publish a 2x2 AXI4-Lite crossbar execution witness and its boundaries."""

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
from protocol_model.integrations.recipes.amba.endpoints import (  # noqa: E402
    build_amba_queued_address_responder_vdut,
)
from protocol_model.integrations.recipes.amba.fabrics import (  # noqa: E402
    build_axi4_lite_address_crossbar_vdut,
)
from protocol_model.protocols.amba.axi.axi4_lite import (  # noqa: E402
    build_axi4_lite_interface,
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
from protocol_model.virtual_dut.address import (  # noqa: E402
    AddressSpace,
    MemoryRegion,
)
from protocol_model.virtual_dut.backend import CaptureBackend, CaptureState  # noqa: E402
from protocol_model.virtual_dut.backend.queued_address import (  # noqa: E402
    constant_address_delay,
)
from protocol_model.virtual_dut.boundary import (  # noqa: E402
    InterfacePort,
    VirtualDut,
)
from protocol_model.virtual_dut.fabric import (  # noqa: E402
    AddressRoute,
    ScheduledAddressCrossbarState,
)
from protocol_model.visualization import (  # noqa: E402
    DiagramDetail,
    VisualizationPublisher,
    interconnect_interface_map_dot,
    project_address_interconnect,
    project_virtual_dut,
    system_topology_dot,
    system_trace_dot,
    virtual_dut_structure_dot,
)


DEMO_NAME = "axi4-lite-2x2-crossbar"
SYSTEM_NAME = "axi4_lite_two_by_two"
INGRESS_QUEUE_CAPACITY = 2


def _manager(name: str, protocol) -> VirtualDut:
    return VirtualDut(
        name,
        {"axi": InterfacePort("axi", protocol, "manager")},
        backend=CaptureBackend(),
        description="externally driven AXI4-Lite manager boundary",
    )


def _target(name: str, protocol, fill: int) -> VirtualDut:
    return build_amba_queued_address_responder_vdut(
        name,
        protocol,
        AddressSpace(
            (
                MemoryRegion(
                    f"{name}_memory",
                    0x100,
                    initial_content=bytes((fill,)) * 0x10,
                ),
            )
        ),
        capacity=2,
        delay_policy=constant_address_delay(0),
        port_name="axi",
    )


def _build_system():
    protocol = build_axi4_lite_interface()
    routes = (
        AddressRoute(
            "target0",
            0x1000,
            0x100,
            "m_target0",
            output_base_address=0,
        ),
        AddressRoute(
            "target1",
            0x2000,
            0x100,
            "m_target1",
            output_base_address=0,
        ),
    )
    router = AddressRouterContract(
        "main_crossbar",
        "crossbar",
        ("s_manager0", "s_manager1"),
        ("m_target0", "m_target1"),
        routes,
    )
    builder = SystemProtocolBuilder(SYSTEM_NAME)
    for dut in (
        _manager("manager0", protocol),
        _manager("manager1", protocol),
        _target("target0", protocol, 0x11),
        _target("target1", protocol, 0x22),
    ):
        builder.add_dut(dut)
    builder.construct_address_router(
        router,
        lambda contract: build_axi4_lite_address_crossbar_vdut(
            contract.router,
            protocol,
            contract.ingress_ports,
            contract.egress_ports,
            contract.routes,
            ingress_queue_capacity=INGRESS_QUEUE_CAPACITY,
        ),
    )
    for name, manager, crossbar_port in (
        ("manager0_bus", "manager0", "s_manager0"),
        ("manager1_bus", "manager1", "s_manager1"),
    ):
        builder.connect(
            name,
            protocol,
            {
                "manager": VirtualDutPortRef(manager, "axi"),
                "subordinate": VirtualDutPortRef("crossbar", crossbar_port),
            },
        )
    for name, crossbar_port, target in (
        ("target0_bus", "m_target0", "target0"),
        ("target1_bus", "m_target1", "target1"),
    ):
        builder.connect(
            name,
            protocol,
            {
                "manager": VirtualDutPortRef("crossbar", crossbar_port),
                "subordinate": VirtualDutPortRef(target, "axi"),
            },
        )
    for target in ("target0", "target1"):
        builder.add_address_claim(
            AddressClaim(
                f"{target}_local",
                VirtualDutPortRef(target, "axi"),
                AddressWindow(0, 0x100),
            )
        )
    return builder.build(), protocol


def _read(manager: str, address: int) -> SystemAction:
    return SystemAction(
        VirtualDutPortRef(manager, "axi"),
        CanonicalEvent("AR", None, {"addr": address, "prot": 0}),
    )


def _crossbar_snapshot(state) -> dict[str, object]:
    crossbar = state.dut_states["crossbar"]
    assert isinstance(crossbar, ScheduledAddressCrossbarState)
    return {
        "advance_index": crossbar.advance_index,
        "ingress_queue_capacity": INGRESS_QUEUE_CAPACITY,
        "ingress_queue_usage": {
            name: len(queue)
            for name, queue in crossbar.ingress_queues.items()
        },
        "active_owners": [
            {
                "request_id": request_id,
                "ingress": owner.ingress_port,
                "egress": owner.egress_port,
            }
            for request_id, owner in sorted(crossbar.pending.items())
        ],
        "round_robin_cursors": dict(crossbar.round_robin_cursors),
    }


def _record(
    label: str,
    action: str,
    outcome: str,
    transition,
) -> dict[str, object]:
    return {
        "label": label,
        "action": action,
        "outcome": outcome,
        "fault": (
            None
            if transition.fault is None
            else {
                "rule": transition.fault.rule,
                "reason": transition.fault.reason,
            }
        ),
        "crossbar": _crossbar_snapshot(transition.state),
        "emissions": [
            {
                "index": item.index,
                "connection": item.connection,
                "source": item.source.qualified_name,
                "destination": item.destination.qualified_name,
                "kind": item.event.kind,
                "payload": dict(item.event.payload),
            }
            for item in transition.emissions
        ],
    }


def _captured(state, manager: str) -> tuple[CanonicalEvent, ...]:
    captured = state.dut_states[manager]
    assert isinstance(captured, CaptureState)
    return tuple(item.event for item in captured.received)


def _execute(system):
    session = system.open_session()
    state = session.initial_state()
    records: list[dict[str, object]] = []
    actions = (
        (
            "S0 · manager0 accepts AR@0x1000",
            "inject manager0.AR",
            "enqueue req0",
            _read("manager0", 0x1000),
        ),
        (
            "S1 · manager1 accepts AR@0x1004",
            "inject manager1.AR",
            "enqueue req1",
            _read("manager1", 0x1004),
        ),
        (
            "S2 · crossbar grants target0 to manager0",
            "advance crossbar",
            "grant req0",
            DutAdvanceAction("crossbar"),
        ),
        (
            "S3 · target0 completes manager0",
            "advance target0",
            "return req0",
            DutAdvanceAction("target0"),
        ),
        (
            "S4 · crossbar grants target0 to manager1",
            "advance crossbar",
            "grant req1",
            DutAdvanceAction("crossbar"),
        ),
        (
            "S5 · target0 completes manager1",
            "advance target0",
            "return req1",
            DutAdvanceAction("target0"),
        ),
    )
    for label, action_name, outcome, action in actions:
        transition = session.step(state, action)
        records.append(_record(label, action_name, outcome, transition))
        if transition.fault is not None:
            raise RuntimeError(
                f"crossbar witness failed at {label}: "
                f"{transition.fault.rule}: {transition.fault.reason}"
            )
        state = transition.state

    manager0 = _captured(state, "manager0")
    manager1 = _captured(state, "manager1")
    if tuple(item.kind for item in manager0) != ("R",):
        raise RuntimeError("manager0 did not receive exactly one read response")
    if tuple(item.kind for item in manager1) != ("R",):
        raise RuntimeError("manager1 did not receive exactly one read response")
    if manager0[0].payload["data"] != 0x11111111:
        raise RuntimeError("manager0 readback mismatch")
    if manager1[0].payload["data"] != 0x11111111:
        raise RuntimeError("manager1 readback mismatch")
    if not session.is_quiescent(state):
        raise RuntimeError("crossbar witness did not reach quiescence")
    return session, state, records


def _categorical_lane(
    name: str,
    values: list[object],
) -> dict[str, object]:
    return {
        "name": name,
        "wave": "=" * len(values),
        "data": [str(value) for value in values],
    }


def _emission_lane(
    records: list[dict[str, object]],
    name: str,
    predicate,
) -> dict[str, object]:
    values: list[str] = []
    for record in records:
        matching = [item for item in record["emissions"] if predicate(item)]
        if not matching:
            values.append("—")
            continue
        labels = []
        for item in matching:
            payload = item["payload"]
            detail = ""
            if item["kind"] == "AR":
                detail = f" @0x{int(payload['addr']):04x}"
            elif item["kind"] == "R":
                response = "OK" if payload["resp"] == "OKAY" else payload["resp"]
                detail = (
                    f" {response} D={int(payload['data']):08x}"
                )
            labels.append(f"e{item['index']} {item['kind']}{detail}")
        values.append(" + ".join(labels))
    return _categorical_lane(name, values)


def _wavejson(records: list[dict[str, object]]) -> dict[str, object]:
    post_states = [record["crossbar"] for record in records]
    owners = []
    cursors = []
    for state in post_states:
        active = [
            owner
            for owner in state["active_owners"]
            if owner["egress"] == "m_target0"
        ]
        if active:
            owner = active[0]
            manager = owner["ingress"].removeprefix("s_manager")
            owners.append(
                f"req{owner['request_id']} · m{manager}"
            )
        else:
            owners.append("free")
        cursor = int(state["round_robin_cursors"]["m_target0"])
        cursors.append(("manager0", "manager1")[cursor])

    return {
        "signal": [
            _categorical_lane(
                "MODEL STEP · not clock",
                [f"S{index}" for index in range(len(records))],
            ),
            [
                "action",
                _categorical_lane(
                    "caller action",
                    [record["action"] for record in records],
                ),
                _categorical_lane(
                    "step outcome",
                    [record["outcome"] for record in records],
                ),
            ],
            [
                "events",
                _emission_lane(
                    records,
                    "manager → crossbar",
                    lambda item: item["source"].startswith("manager"),
                ),
                _emission_lane(
                    records,
                    "crossbar → target0",
                    lambda item: item["source"] == "crossbar.m_target0",
                ),
                _emission_lane(
                    records,
                    "target0 → crossbar",
                    lambda item: item["source"] == "target0.axi",
                ),
                _emission_lane(
                    records,
                    "crossbar → manager",
                    lambda item: item["source"].startswith("crossbar.s_manager"),
                ),
            ],
            [
                "post-state",
                _categorical_lane(
                    "q[s_manager0] usage",
                    [
                        f"{state['ingress_queue_usage']['s_manager0']}/"
                        f"{state['ingress_queue_capacity']}"
                        for state in post_states
                    ],
                ),
                _categorical_lane(
                    "q[s_manager1] usage",
                    [
                        f"{state['ingress_queue_usage']['s_manager1']}/"
                        f"{state['ingress_queue_capacity']}"
                        for state in post_states
                    ],
                ),
                _categorical_lane("target0 active owner", owners),
                _categorical_lane("target0 RR next scan", cursors),
                _categorical_lane(
                    "crossbar advance_index",
                    [state["advance_index"] for state in post_states],
                ),
            ],
        ],
        "head": {
            "text": (
                "AXI4-Lite 2×2 crossbar · shared-egress model-step witness"
            )
        },
        "foot": {
            "text": (
                "1 column = 1 completed SystemSession action/service "
                "opportunity · POST-STATE · NOT ACLK, AXI pins, RTL or VCD"
            )
        },
        "config": {"hscale": 5},
    }




def _crossbar_structure_dot(crossbar: VirtualDut) -> str:
    dot = virtual_dut_structure_dot(project_virtual_dut(crossbar))
    dot = dot.replace("  rankdir=LR;", "  rankdir=TB;", 1)
    return "\n".join(
        line for line in dot.splitlines() if "active ownership" not in line
    ) + "\n"


def _stack_trace_components(dot: str) -> str:
    return dot.replace(
        "splines=polyline];",
        'splines=polyline, pack=true, packmode="array_u1"];',
        1,
    )


def _trace_conformance_dot() -> str:
    """Explain why a deterministic witness is not a cycle golden trace."""

    return r'''digraph trace_conformance {
  rankdir=TB;
  label="Bridge trace comparison · contract, witness, and legal stutter";
  labelloc="t";
  graph [bgcolor="white", pad=0.25, nodesep=0.28, ranksep=0.55,
         splines=polyline, newrank=true];
  node [fontname="sans-serif", fontsize=10, shape=box,
        style="rounded,filled", fillcolor="#ffffff"];
  edge [fontname="sans-serif", fontsize=9, color="#52606d"];

  contract [shape=note, fillcolor="#eff6ff", color="#2563eb",
    label="Bridge contract\noperation/result relation · correlation · required partial order\noptional latency or exact-cycle constraints"];

  subgraph cluster_witness {
    label="One deterministic execution witness · model service steps";
    color="#94a3b8"; style="rounded";
    { rank=same;
      wa [label="accept A"];
      wi [label="issue child A"];
      wc [label="complete child A"];
      wr [label="return A"];
    }
    wa -> wi -> wc -> wr;
  }

  subgraph cluster_rtl {
    label="Illustrative RTL schedule after pin-local protocol checks";
    color="#94a3b8"; style="rounded";
    { rank=same;
      ra [label="accept A"];
      rs0 [shape=ellipse, style="dashed,filled", fillcolor="#f8fafc",
           label="stall / no transfer"];
      rs1 [shape=ellipse, style="dashed,filled", fillcolor="#f8fafc",
           label="idle"];
      ri [label="issue child A"];
      rs2 [shape=ellipse, style="dashed,filled", fillcolor="#f8fafc",
           label="wait"];
      rc [label="complete child A"];
      rr [label="return A"];
    }
    ra -> rs0 -> rs1 -> ri -> rs2 -> rc -> rr;
  }

  subgraph cluster_projection {
    label="Normalized observable behavior";
    color="#16a34a"; style="rounded";
    { rank=same;
      na [label="accept A", fillcolor="#f0fdf4"];
      ni [label="issue A", fillcolor="#f0fdf4"];
      nc [label="complete A", fillcolor="#f0fdf4"];
      nr [label="return A", fillcolor="#f0fdf4"];
    }
    na -> ni -> nc -> nr [label="required happens-before"];
  }

  contract -> wa [label="execution profile chooses one schedule"];
  contract -> ra [label="RTL may choose another allowed schedule"];
  wr -> na [style=dashed, color="#16a34a", label="project witness"];
  rr -> na [style=dashed, color="#16a34a",
    label="observe transfers; erase irrelevant stutter"];

  verdict [shape=note, fillcolor="#fff7ed", color="#ea580c",
    label="Default conformance: projected RTL ∈ allowed behaviors\nnot: raw RTL cycles == witness cycles\nExact cycle equality requires an explicit PIN_CYCLE contract"];
  nr -> verdict;
}
'''


def _readme() -> str:
    return """# AXI4-Lite 2×2 crossbar · executable witness

这个发布包来自具名脚本实际装配和执行的 `SystemProtocol`，不是手工绘制的假想网络。

## 1. 网络拓扑

![2×2 topology](topology.svg)

两个 manager 各通过一条完整的 AXI4-Lite interface connection 进入 crossbar；
两个 target 分别位于另一侧。该图只表示 module 与 connection，不从星形外观推断
crossbar 内部的通道数、仲裁或路由行为。

## 2. Interconnect interface map

![interconnect interface map](interconnect-interface-map.svg)

这张图显式选择 `crossbar` 的 address-router contract，把两侧真实 port/role 和
地址窗投影出来。System route contract 将系统窗口 `0x1000`、`0x2000` remap
到 target 的局部 `0x0..0xff`。边上显示协议身份；connection 实例名保存在 typed
view 中，并只在 diagnostic 密度显示。中央矩形表示一个多端口 `VirtualDut` 的
边界，不代表物理共享总线或固定数量的内部 crosspoint。

## 3. Crossbar VirtualDut 内部构造

![crossbar structure](crossbar-structure.svg)

实线是 request 主路径：attachment 解出完整 address access，地址先完成
decode/remap，再进入相应 ingress FIFO；每个 egress 有独立 round-robin arbiter。
点线表示 owner/cursor 控制关系，虚线表示 completion 返回。owner table 保存
`request_id → ingress/egress` 相关性，不是 request 数据必经的转换级。

## 4. 模型步骤执行视图

![model-step execution view](model-steps.svg)

横向六列分别对应六次已经完成的 `SystemSession` action。S0、S1 是外部
request 注入，S2、S4 是 crossbar 的显式 service opportunity，S3、S5 是
target0 的显式 service opportunity。列宽只服务排版，不表示物理持续时间、相邻
硬件周期或共同 clock。

Canonical-event lanes 显示本步实际接受并路由的事件；状态 lanes 是本步结束后的
reference backend post-state。`RR next scan` 表示下一次仲裁扫描起点，不表示当前
owner。S3/S5 同列出现 downstream R 与 upstream R，表示一次模型调用内的
fixed-point 传播，不能据此推断 RTL 在同一周期返回。

## 5. 同出口竞争因果见证

![contention causality](causality.svg)

manager0 和 manager1 都访问 target0。当前 execution profile 用显式 service
opportunity 先授予 manager0，completion 返回后再授予 manager1。这个结果证明
当前 constructed backend 的 FIFO、lease 和 return owner 可以协同执行；它不把
round-robin 的这一条线性展开提升为所有外部 RTL 必须逐周期复制的波形。

当前 `SystemTrace` 只画运行时已经声明的 causal edge。由独立
`DutAdvanceAction` 触发的 delayed grant 尚未携带最初 ingress event 的完整 lineage，
因此本图不能被解读成完整的端到端因果证明。

## 6. Reference witness 与 RTL conformance

![trace conformance](trace-conformance.svg)

桥或 crossbar contract 描述一组允许行为；deterministic executor 只从中选择一条
execution witness。RTL pin frame 必须先接受协议本地检查，例如 handshake、stall
期间稳定性、reset 和不可回压条件。之后，operation/effect 级比较可以折叠没有
相关 transfer/effect 的 stutter frame，并检查 identity、结果和必要偏序。

因此普通判定形式是：

```text
normalize(observe(RTL frames)) ∈ AllowedBehaviors(contract)
```

而不是：

```text
RTL frames == generated witness frames
```

如果 profile 声明最大延迟、吞吐、progress 或 `PIN_CYCLE` 等价，相关空周期就不再
是无关 stutter，必须在折叠前或由独立 property 检查。当前工程尚未实现通用 RTL
conformance/partial-order checker；本图记录目标边界，不声称该 checker 已完成。

机器可读运行见 [result.json](result.json)，图源在 [sources](sources/)，生成边界见
[provenance.json](provenance.json)，完整文件清单见 [manifest.json](manifest.json)。
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
    session, state, records = _execute(system)
    store = RunArtifactStore("vdut-axi4-lite-2x2-crossbar", directory)
    publisher = VisualizationPublisher(store)
    interface_map = project_address_interconnect(
        system.elaborate(), interconnect="crossbar"
    )
    interface_map_detail = DiagramDetail.STANDARD
    interface_map_descriptor = interface_map.descriptor(
        detail=interface_map_detail
    )

    publisher.render_wave(
        "model-steps",
        _wavejson(records),
        kind="execution_step_view",
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
            title=(
                "AXI4-Lite 2×2 address network · interface boundary view"
            ),
        ),
        kind=interface_map_descriptor.view_kind.value,
    )
    publisher.render_dot(
        "crossbar-structure",
        _crossbar_structure_dot(system.virtual_duts["crossbar"]),
        kind="vdut_structure",
    )
    publisher.render_dot(
        "causality",
        _stack_trace_components(
            system_trace_dot(
                session.trace(state),
                title="AXI4-Lite 2×2 crossbar · shared-egress witness",
            )
        ),
        kind="causality",
    )
    publisher.render_dot(
        "trace-conformance",
        _trace_conformance_dot(),
        kind="architecture_explanation",
    )

    store.write_json(
        "result.json",
        {
            "schema": "protocol-model.showcase.axi4-lite-crossbar/v1",
            "system": {
                "name": system.name,
                "virtual_duts": list(system.virtual_duts),
                "connections": list(system.connections),
            },
            "steps": records,
            "assertions": {
                "fault_free": True,
                "shared_egress_serialized": True,
                "manager0_readback": "0x11111111",
                "manager1_readback": "0x11111111",
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
            "source": (
                "showcase/demos/vdut/axi4_lite_2x2_crossbar/run.py"
            ),
            "command": (
                "python3 "
                "showcase/demos/vdut/axi4_lite_2x2_crossbar/run.py"
            ),
            "protocol_model_version": __version__,
            "execution_models": [
                "SystemSession",
                "ScheduledAddressCrossbarBackend",
                "QueuedAddressResponderBackend",
            ],
            "renderers": {
                "topology": "Graphviz dot + shared system topology projection",
                "interconnect_interface_map": (
                    "Graphviz dot + shared typed address-interconnect "
                    "projection"
                ),
                "model_steps": (
                    "WaveDrom 3.6.2 + model-step state projection"
                ),
                "vdut_structure": (
                    "Graphviz dot + shared VirtualDut projection, "
                    "demo-local vertical arrangement"
                ),
                "causality": (
                    "Graphviz dot + shared trace projection, disconnected "
                    "transactions stacked for reading"
                ),
                "trace_conformance": (
                    "Graphviz dot + demo-local explanatory projection"
                ),
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
                "transaction-semantic execution witness with explicit service "
                "opportunities; not raw RTL, a cycle golden trace, or a "
                "completed RTL conformance checker"
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
                "name": "shared-egress-contention",
                "expected": (
                    "manager0 then manager1 own target0 and receive the "
                    "matching completion"
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
            "publication": (
                "showcase/generated/vdut/axi4-lite-2x2-crossbar"
            ),
            "network_scope": "non-coherent AXI4-Lite 2x2 address network",
            "raw_pin_capture": False,
            "reference_role": "execution_witness_not_cycle_golden",
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
        description="Publish the AXI4-Lite 2x2 crossbar witness."
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
            "model-steps.svg",
            "sources/model-steps.json",
            "topology.svg",
            "sources/topology.dot",
            "interconnect-interface-map.svg",
            "sources/interconnect-interface-map.dot",
            "crossbar-structure.svg",
            "sources/crossbar-structure.dot",
            "causality.svg",
            "sources/causality.dot",
            "trace-conformance.svg",
            "sources/trace-conformance.dot",
            "provenance.json",
        ):
            if not (staged / required).is_file():
                raise RuntimeError(f"staged demo lacks {required}")
        _publish(staged, target)

    try:
        build_root.rmdir()
    except OSError:
        pass
    print(f"Published AXI4-Lite crossbar demo: {target}")
    print(f"Manifest: {target / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
