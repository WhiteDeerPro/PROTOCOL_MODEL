# Code Map

```text
protocol_model/
├── core/                    # SemanticComponent、step、fault、verdict
├── domains/                 # symbolic value与EventSpace
├── semantics/               # cardinality、correlation token
├── patterns/                # ready-valid、two-phase、reset、quiet
├── protocols/
│   ├── spec.py              # ProtocolSpec IR
│   ├── session.py           # per-link runtime state product
│   ├── axi4/
│   ├── apb/
│   │   └── evidence.py      # APB专用renderer归协议包
│   └── ready_valid/         # 单通道参数化ProtocolSpec
├── virtual_dut/
│   ├── base.py              # VirtualDut kind/contract/descriptor
│   ├── primitives.py        # Sink、ScriptedSource、FunctionResponder
│   └── registry.py          # 公共原语factory registry
├── projects/
│   ├── base.py              # lifecycle、inventory、state、artifacts
│   ├── prj_ready_valid_sink/# Source → Protocol → Sink最小项目
│   │   ├── project.py       # case与runtime state
│   │   ├── simulation.py    # 默认plan与sims目录构造
│   │   └── evidence.py      # waveform/event/topology renderer
│   └── prj_axi4_read_bridge/
│       ├── project.py       # cases与执行计划
│       ├── network.py       # 该项目的link runtime/provenance
│       ├── virtual_dut_bridge.py
│       ├── virtual_dut_responder.py
│       └── evidence.py      # 该项目专用报告
├── engine/trace.py          # finite trace + causal graph
├── evidence/                # 跨项目通用renderer
└── relations.py             # strict partial order
```

依赖方向：

```text
core/domains
    ↓
semantics/patterns
    ↓
protocols
    ↓
virtual_dut + projects
    ↓
artifacts
```

网络 topology 属于具体 Project 的 verification plan。只有多个 Project 证明某个网络机制
完全相同，才提升为通用层。
