# Interface-local contracts

`protocol_model.interface` 提供与具体标准无关的接口合同和可执行 session。这里的 **interface** 是判定
作用域：一条规则只需要观察一个完整逻辑接口，就可以在这里运行。它不表示物理层，也不对应 CHI 的
Protocol、Network 或 Link layer。

当前公共对象包括：

- `InterfaceProtocol`：roles、directed event kinds、event schemas、局部约束和 monitors 的不可变声明；
- `InterfaceSession`：一份连接实例的局部运行状态；
- `InterfaceEventKind`：把一个 event schema 绑定到 source/destination role；它不自动表示标准中的独立
  wire channel。AXI AW/W/B 之类的标准 channel 名称仍由具体协议包解释。

Event schema 位于 `protocol_model.semantics`，因为一次通信事实不专属于 interface scope。AXI、AHB、
APB、TileLink 和 CHI 等具体标准位于 `protocol_model.protocols`，它们可以使用本包，也可以同时使用
representation、transport、VirtualDut 和 system 设施。通用 interface 内核不反向导入具体协议族。

transport link 表示单向 transmitter→receiver hop；当前由 `ChiTransportLink` 等协议族具体对象实现，
通用层没有同名公共基类。它不表示 AXI channel bundle，也不表示 SystemProtocol 中把完整逻辑接口绑定
起来的 `InterfaceConnection`。
