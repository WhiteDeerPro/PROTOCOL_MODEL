# Interface-local contracts

`protocol_model.interface` 提供标准无关的接口合同和可执行 session。这里的 **interface** 指判定作用域：
只需观察一个完整逻辑接口的规则在此声明和运行。物理层次以及 CHI Protocol、Network、Link layer 的含义由
对应协议族表达。

## 公共对象

| 对象 | 输入 | 产出与生命周期 |
|---|---|---|
| `InterfaceProtocol` | roles、directed event kinds、event schemas、局部约束和 monitors | 一个完整逻辑接口的不可变合同 |
| `InterfaceSession` | `InterfaceProtocol` 与连接实例收到的 events | 该连接实例的局部运行状态和 monitor 结果 |
| `InterfaceEventKind` | event schema、source role 和 destination role | 带方向的接口事件种类 |

`InterfaceEventKind` 描述合同中的事件方向；AXI AW/W/B 等 wire channel 名称及其标准含义由具体协议包解释。

## 输入与相邻交接

- `protocol_model.semantics` 提供 scope-neutral event schema 和共同值对象。
- `protocol_model.protocols` 将 AXI、AHB、APB、TileLink、CHI 等标准规则具体化为接口合同；依赖方向从具体协议
  指向本包的通用内核。
- `protocol_model.system` 使用 `InterfaceConnection` 把完整逻辑接口绑定到 module ports，并在更大的判定范围内
  组合系统合同。
- 协议族中的 transport 对象表达单向 transmitter→receiver hop，例如 `ChiTransportLink`。AXI channel bundle
  由 AXI 协议对象表达，完整接口连接由 `InterfaceConnection` 表达。
