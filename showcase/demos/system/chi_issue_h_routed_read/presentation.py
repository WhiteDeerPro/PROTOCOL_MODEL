"""Tutorial projections for the routed CHI read showcase."""

from __future__ import annotations

import json


def _quoted(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def transaction_path_dot(result: dict[str, object]) -> str:
    """Show the forward REQ and reverse DAT paths as model actions."""

    request = result["request"]
    response = result["response"]
    lines = [
        "digraph chi_routed_transaction {",
        "  rankdir=LR;",
        '  graph [bgcolor="white", pad=0.35, nodesep=0.48, ranksep=0.85, '
        'splines=polyline, outputorder=edgesfirst, labelloc="t", fontsize=16, '
        'label="CHI Issue H · routed ReadNoSnp model path"];',
        '  node [fontname="sans-serif", fontsize=10, shape=box, '
        'style="rounded,filled", margin="0.10,0.07"];',
        '  edge [fontname="sans-serif", fontsize=9, penwidth=1.8];',
        '  req_rn [group="rn", fillcolor="#dbeafe", color="#2563eb", '
        'label="RN-I\nissue ReadNoSnp"];',
        '  req_xp0 [group="xp0", fillcolor="#ecfdf5", color="#059669", '
        'label="XP0\naccept + store + forward"];',
        '  req_xp1 [group="xp1", fillcolor="#ecfdf5", color="#059669", '
        'label="XP1\naccept + store + forward"];',
        '  req_home [group="home", fillcolor="#ffedd5", color="#ea580c", '
        'label="I/O Home\naccept request"];',
        '  dat_home [group="home", fillcolor="#ffedd5", color="#ea580c", '
        'label="I/O Home\nAddressTarget read"];',
        '  dat_xp1 [group="xp1", fillcolor="#f3e8ff", color="#9333ea", '
        'label="XP1\naccept + store + forward"];',
        '  dat_xp0 [group="xp0", fillcolor="#f3e8ff", color="#9333ea", '
        'label="XP0\naccept + store + forward"];',
        '  dat_rn [group="rn", fillcolor="#dbeafe", color="#2563eb", '
        'label="RN-I\ncorrelate CompData\nrelease outstanding"];',
        "  req_rn -> req_xp0 [color=\"#059669\", "
        f"label={_quoted('REQ 0 · Addr=' + hex(request.address))}];",
        '  req_xp0 -> req_xp1 [color="#059669", label="REQ 1"];',
        '  req_xp1 -> req_home [color="#059669", label="REQ 2"];',
        '  req_home -> dat_home [color="#ea580c", label="local service"];',
        '  dat_home -> dat_xp1 [color="#9333ea", '
        f"label={_quoted('DAT 0 · Data=' + hex(response.data))}];",
        '  dat_xp1 -> dat_xp0 [color="#9333ea", label="DAT 1"];',
        '  dat_xp0 -> dat_rn [color="#9333ea", label="DAT 2"];',
        '  { rank=same; req_rn; dat_rn; }',
        '  { rank=same; req_xp0; dat_xp0; }',
        '  { rank=same; req_xp1; dat_xp1; }',
        '  { rank=same; req_home; dat_home; }',
        '  note [shape=note, fillcolor="#f8fafc", color="#64748b", '
        'label="Each arrow is a committed model transfer across one directed '
        'transport hop.\nIt is not a raw waveform and does not prescribe RTL '
        'cycle spacing."];',
        "  dat_rn -> note [style=dashed, color=\"#94a3b8\"];",
        "}",
    ]
    return "\n".join(lines) + "\n"


def lineage_dot(result: dict[str, object]) -> str:
    """Render the actual end-to-end lineage carried by the execution."""

    lineage = (*result["lineage"], "sensor_reader.reads.complete")
    lines = [
        "digraph chi_routed_lineage {",
        "  rankdir=TB;",
        '  graph [bgcolor="white", pad=0.35, nodesep=0.35, ranksep=0.42, '
        'splines=line, labelloc="t", fontsize=16, '
        'label="Committed lineage · request to completion"];',
        '  node [fontname="monospace", fontsize=10, shape=box, '
        'style="rounded,filled", margin="0.10,0.06"];',
        '  edge [color="#64748b", penwidth=1.5];',
    ]
    for index, label in enumerate(lineage):
        if label.endswith(".issue") or label.endswith(".complete"):
            fill, color = "#dbeafe", "#2563eb"
        elif label.endswith(".service"):
            fill, color = "#ffedd5", "#ea580c"
        elif label.startswith("req_"):
            fill, color = "#ecfdf5", "#059669"
        else:
            fill, color = "#f3e8ff", "#9333ea"
        lines.append(
            f"  event{index} [fillcolor={_quoted(fill)}, "
            f"color={_quoted(color)}, label={_quoted(f'E{index} · {label}')}];"
        )
        if index:
            lines.append(f"  event{index - 1} -> event{index};")
    lines.extend(
        (
            '  boundary [shape=note, fontname="sans-serif", '
            'fillcolor="#f8fafc", color="#64748b", '
            'label="Labels are produced by the executed lineage sidecar.\n'
            'They prove model-level causal custody, not physical timing."];',
            f"  event{len(lineage) - 1} -> boundary "
            '[style=dashed, color="#94a3b8"];',
            "}",
        )
    )
    return "\n".join(lines) + "\n"


def guide(result: dict[str, object]) -> str:
    """Build the generated, result-specific reading guide."""

    profile = result["profile"]
    request = result["request"]
    response = result["response"]
    outcome = result["result"]
    return f"""# CHI Issue H：两级 XP 路由读取

![自动拓扑图](topology.svg)

这个示例由 `SystemProtocolBuilder` 声明四个 VirtualDut 和六条有向 transport connection：
`sensor_reader_rn → xp0 → xp1 → sensor_io_home` 承载 REQ，DAT 沿独立的反向连接返回。
拓扑图直接从实际 `SystemProtocol` 生成，不另存一份手写网络事实。

![事务路径](transaction-path.svg)

RN-I 以 `NodeID={profile['requester_node_id']:#x}` 发出 `ReadNoSnp`，目标 Home 为
`NodeID={profile['home_node_id']:#x}`。请求地址 `{request.address:#x}` 经过两个有限
store-and-forward XP；I/O Home 通过通用 `AddressSpace/MemoryRegion` 读取并返回
`{response.data:#x}`，随后 RN-I 以 TxnID 关联 `CompData` 并释放 outstanding。

![执行 lineage](lineage.svg)

lineage 图来自本次执行实际保留的 custody 标签。它把 requester issue、每条 REQ/DAT hop、Home
service 和 completion 连成一条因果证据链；它不把 reference scheduler 的空步或 link tick 写成 RTL
必须遵守的周期位置。

## 本次实际检查

- REQ 与 DAT 分别解析为三条有向 connection；
- 两个 XP 都执行了 accept、有限队列暂存和 downstream forward；
- 每跳 activation、L-Credit、TX/RX 容量和背压仍由现有 CHI transport session 执行；
- typed payload 在普通路由中保持不变；
- completion lineage 覆盖全部六条 hop；
- 返回值、DataID、transaction correlation 和最终静默状态均通过检查；
- reference scheduler 共提交 `{outcome['committed_microsteps']}` 个 microstep。

## 外设表示边界

`sensor_io_home` 使用 `ChiAddressHomeNode` 把 CHI `ReadNoSnp` 降为协议无关的 `AddressRead`，并由
`AddressSpace/MemoryRegion` 持有唯一的本地数据状态。当前绑定属于 CHI family participant composition；
全局 address→Home authority 仍是后续 SystemProtocol 合同。

## 当前范围

这是 direct-Home、aligned full-DAT-width、single-DAT-flit、REQ/DAT-only 的 CHI Issue H 参考见证。
完整 CHI Port、raw pin waveform、bit codec、narrow DAT placement、CHI error-response mapping、
SNP/coherence、multi-flit response、router QoS/fairness 和网络死锁证明仍在本例范围之外。
图中的箭头表达模型级传输与因果次序，不约束真实 RTL 在相邻传输之间插入多少空拍。

机器结果见 [result.json](result.json)，可检查的 DOT 源见 [sources](sources/)，生成方式和边界见
[provenance.json](provenance.json)。
"""


__all__ = ["guide", "lineage_dot", "transaction_path_dot"]
