# Integration 源码导航

`integrations` 汇合具体 `InterfaceProtocol` 资产与 VirtualDut operation/构造合同。这里的代码同时理解线上协议
和 module 行为，并按产物角色形成单向依赖。

## 四类构件

| 构件 | 核心职责 | 产物与使用者 |
|---|---|---|
| `attachments/` | 单端口 event ↔ operation 转换及接口侧状态 | binding 与 attachment-aware backend |
| [`translations/`](translations/README.md) | 可复用的 protocol-bound typed stage 与 plan fragment | bridge plan 和 recipe |
| [`backends/`](backends/README.md) | 受协议 channel、ID、ordering 约束的跨端口执行状态 | concrete VirtualDut realization |
| [`recipes/`](recipes/README.md) | 选择 port、binding、profile、translation 与 backend | 可直接构造的 `VirtualDut` |

```text
protocols/<family> + virtual_dut contracts
              │
              ├── attachments ───────┐
              ├── translations ──────┼──> backends ──┐
              │                      └───────────────┼──> recipes
              └──────────────────────────────────────┘
```

AXI ID/channel ordering 等协议规则会直接塑造跨端口 controller。对应实现位于
[`backends/amba/axi/axi4/`](backends/amba/axi/axi4/)，recipe 负责选择并装配这些实现。可由协议无关
operation、fabric 或 translation backend 表达的行为继续复用 `virtual_dut/`。

## 选择放置位置

1. 单个端口的协议解释和局部状态进入 `attachments/`。
2. 多个 plan 复用的 typed lower/lift 进入 `translations/`。
3. 具体协议直接决定跨端口 FIFO、owner、route lock 或 transaction lifecycle 时，进入 `backends/`。
4. 最终构造函数进入 `recipes/`，并由其绑定 concrete ports 与 profiles。

`recipes/` 按 endpoint、fabric、bridge 和 control module 分类公共构造入口。网络中的具名实例由 system、
scenario 或调用方 project 持有。AMBA qualifier 描述端口绑定范围；module identity 仍由具体
`VirtualDut` 的系统角色决定。跨 family 产品放在相应的 cross-family recipe scope，并复用语义一致的通用构件。
