# Runtime

本包承载 SystemAction、session state、SystemEvent/SystemTrace、fixed-point 路由、显式推进、scheduler 和
延迟 emission lineage。Runtime 只执行已固定的 topology/resolved plan，不负责搜索 bridge 或修正不兼容连接。

根 `SystemSession` 目前执行 `InterfaceConnection` 的 canonical event 传播。transport family 在自己的叶包内
执行 `ElaboratedSystemProtocol.transport_plan`：CHI Issue H 已提供一个读取调用方拓扑的 session，统一保存
hop/router 状态和 lineage。这种安排让通用 runtime 不反向依赖 CHI，同时保留唯一 topology 权威。

deferred emission 的原 ingress causal lineage、通用 scheduler 与 interface/transport 的统一 action loop 仍是后续收敛点；
crossbar FIFO/仲裁和事务时空图都依赖这些投影。
