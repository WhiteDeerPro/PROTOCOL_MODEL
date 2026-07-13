# Roadmap

## M0：统一语义核心

- [x] `SemanticComponent` state/action/step/emission/fault；
- [x] signal、transaction、session 使用同一接口；
- [x] causal predecessors 进入 `SemanticStep`；
- [x] 删除旧 component、request-response、兼容层和生成核心；
- [x] EventSpace、三值 verdict、有限偏序 trace。

## M1：协议模式与协议包

- [x] ready-valid、stall stability、reset epoch；
- [x] APB3/APB4 two-phase；
- [x] AXI4 五通道、burst、4KB、WSTRB；
- [x] AR/R cardinality、AW/W join、B obligation、per-ID token；
- [x] WaveDrom、Graphviz 与 constraint witness；
- [ ] exclusive/capability/USER 和完整 ordering model；
- [ ] one-of conflict、静态 independence、deadline。

## M2：Verification Project

- [x] Project lifecycle、component inventory、state、artifacts；
- [x] `prj_ready_valid_sink` 最小 Source → Protocol → Sink 竖切；
- [x] 独立命名项目包 `prj_axi4_read_bridge`；
- [x] 两个独立 AXI link state；
- [x] Project 内 global provenance 和因果图；
- [x] expected violation 被判为 CHECKED，而非 FAILED；
- [x] 多 case plan、case artifact 与 project summary；
- [ ] case selection；
- [ ] 通用但不过早抽象的 topology elaboration。

## M3：VirtualDut

- [x] VirtualDut kind、contract、capability 和 registry；
- [x] Sink、ScriptedSource、FunctionResponder 基础原语；
- [x] read forwarding bridge、ID remap 和 correlation；
- [x] terminating dumb read responder；
- [ ] latency/backpressure policy；
- [ ] memory/register state 与 Hoare-style contract；
- [ ] write bridge、width conversion 和 arbitration；
- [ ] deadlock、fairness 和 resource invariant。

## M4：外部验证工程

- [ ] canonical event JSON schema；
- [ ] VCD/FSDB/UVM adapter；
- [ ] partial probe、InterfaceProfile 和 coverage report；
- [ ] waveform event 回链与最小 violation slice。

默认按语义 witness 推进，不用测试数量替代可解释证据。
