# Construction

本包提供 `SystemProtocolBuilder`，用于显式加入 VirtualDut、InterfaceConnection、
DirectedTransportConnection、system boundary 和 address contract。`connect()` 绑定完整逻辑接口，
`connect_transport()` 绑定单向 transmitter→receiver hop；它们进入同一份 SystemProtocol topology。

`construct_address_router(contract, factory)` 通过注入 factory 构造 router：System 把同一份
route contract 交给 factory，并比较 backend 实际公开的 `AddressRouterBoundaryProjection`；System 不导入
AMBA，也不接管 router 的 FIFO、仲裁或 owner 状态。factory 不公开 projection 或配置不同 route 时，
construction 在注册 DUT 前失败。

`add_dut()` + `add_address_router()` 表示外部/opaque DUT 的显式合同假设。当前不会把这类假设与 RTL/RPC
实现自动核对；以后由 external boundary projection adapter 补上该证据。

后续经调用方授权的 translation-plan lowering 仍可沿用同一边界；最终结果必须是普通、显式的
SystemProtocol topology。

Construction 不在 SystemSession 运行时偷偷插入 adapter，也不把生成节点隐藏在另一套路由语义中。
