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
