# Contracts

本包声明只有系统作用域才拥有的权威事实和性质。首条已实现的 vertical slice 是 address contract：
`AddressClaim` 声明接收边界的本地窗口，`AddressRouterContract` 显式声明一个 routing VirtualDut 的入口、
出口和 `AddressRoute` 表，`AddressMapContract` 聚合二者。Topology 的 N×M 外观不会自动产生这些声明。

home/identity、path capability、clock/reset/security/coherence membership，以及 fairness/latency property
仍按真实场景逐步加入。

Contract 是不可变意图，不保存 bridge FIFO、crossbar arbiter 或真实 directory 等 VirtualDut 私有运行状态。
局部实现通过 boundary projection 与 resolved contract 闭合。
