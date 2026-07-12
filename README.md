# Protocol Model

Protocol Model 是一个实验性的协议语义与有限 trace 引擎。当前目标是用同一套
`SemanticComponent.step(state, action)` 语义完成合法行为构造、外部 trace 验证、事务
义务和因果图生成。

## 语义主线

```text
pin observation
  → handshake/phase SemanticComponent
  → canonical transfer event
  → cardinality/correlation SemanticComponent
  → transaction state + causal edges + verdict
```

所有状态机、token monitor 和 protocol session 都派生自
[`SemanticComponent`](protocol_model/core/component.py)。旧的
`ProtocolComponent + ProtocolSnapshot + propose/reject/transition` 生成体系已经删除。

## 当前协议

- AXI4：五通道 ready-valid、reset epoch、AR/R cardinality、AW/W ordered join、
  WLAST/RLAST、B obligation、ID ordering、burst geometry、WSTRB byte lanes、并发 session；
- APB3/APB4：SETUP/ACCESS、PREADY wait、PSLVERR，以及 APB4 PSTRB/PPROT；
- Quiet：IGNORE/STABLE/TIED 端口观测策略。

已具有首个 VirtualDut + 双 AXI link Project；尚未建模通用 topology、FSDB/VCD adapter、
完整 AXI exclusive/capability/USER 和功能 memory 内容。

## 可视化证据

以下 SVG 是当前两个验证 Project 的固定示例证据。每次运行仍会在各 Project 的
`sims/` 下生成可丢弃的完整报告；此处仅保留适合快速理解项目的代表性图。

<table>
  <tr>
    <td width="50%" valign="top">
      <strong>Ready-valid：合法 stall 后的 transfer</strong><br>
      <img src="protocol_model/projects/prj_ready_valid_sink/sims/01/legal.wave.svg" alt="Ready-valid legal waveform" width="580">
    </td>
    <td width="50%" valign="top">
      <strong>Ready-valid：协议接受后的因果事件</strong><br>
      <img src="protocol_model/projects/prj_ready_valid_sink/sims/01/legal.events.svg" alt="Ready-valid causal event graph" width="580">
    </td>
  </tr>
</table>

<p align="center">
  <strong>AXI4 read bridge：两条 AXI link、桥接 VirtualDut 与响应端之间的因果链</strong><br>
  <img src="protocol_model/projects/prj_axi4_read_bridge/sims/01/axi_read_chain.svg" alt="AXI4 read bridge causal chain" width="860">
</p>

## 可执行证据

```bash
.venv/bin/python -m protocol_model constraint-witness
.venv/bin/python -m protocol_model waveform --channel AW
.venv/bin/python -m protocol_model read-transaction
.venv/bin/python -m protocol_model write-transaction --graph-dir artifacts/axi4_write
.venv/bin/python -m protocol_model session --reads 2 --writes 2 --artifacts-dir artifacts/axi4_session
.venv/bin/python -m protocol_model apb --transactions 1 --artifacts-dir artifacts/apb
.venv/bin/python -m protocol_model axi-read-network
.venv/bin/python -m protocol_model ready-valid-sink
```

WaveDrom 使用项目本地 npm 依赖；Python 只支持工作区 `.venv`。

## 文档

- [架构故事](docs/architecture.md)
- [代码地图](docs/code_map.md)
- [形式语义](docs/semantics.md)
- [理论审计](docs/theory_audit.md)
- [AXI4 派生](docs/axi4_derivation.md)
- [AXI4 约束来源审计](docs/axi4_constraint_audit.md)
- [APB 派生](docs/apb_derivation.md)
- [验证 Projects](docs/verification_projects.md)
- [VirtualDut 方法](docs/virtual_dut.md)
