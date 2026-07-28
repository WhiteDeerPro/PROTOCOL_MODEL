# Resolution

本包承载 structure、capability、address、identity 和 domain closure passes，并产生不可变 resolved plan。
当前 `elaboration.py` 在结构闭合与 semantics namespace 之后调用 address pass：它只把显式 router route
闭合到同一 egress connection 上唯一、覆盖 translated window 的 direct-neighbor claim，并按 ingress×route 形成
`ResolvedAddressPath`。它不搜索 bridge chain，也不根据 topology 猜测路由行为。

`resolve_transport_connections()` 把同一 canonical topology 中的 `DirectedTransportConnection` 投影为
不可变 `ResolvedTransportPlan`，包含具名 hop 以及按端口的 incoming/outgoing 查询。该 pass 不路由 packet，
不展开 mesh/ring，也不另建一份 transport graph；具体 family session 消费 profile 和已解析 hop。

Resolution 不修改已经构造的 frozen VirtualDut。当前 generated address router 在 construction 阶段已把
backend projection 与 contract 核对；resolution 消费该 contract 完成 direct-neighbor closure。外部实现的
projection adapter 与自动核对仍是后续工作。
