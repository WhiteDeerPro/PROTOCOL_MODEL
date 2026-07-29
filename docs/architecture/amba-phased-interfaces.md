# AHB-Lite 与 APB phased InterfaceProtocol

AHB-Lite 和 APB 各自定义点到点可判定的 `InterfaceProtocol`，并采用各自的 pin/cycle phase：

```text
AHB-Lite InterfaceProtocol ──┐
                        ├── AHB→APB bridge VirtualDut ──► two independent links
APB InterfaceProtocol ───────┘
```

bridge module 保存 AHB request、驱动 APB SETUP/ACCESS，并把 APB completion 转回 AHB data phase。
AHB 和 APB 分别判定各自接口合同，bridge backend 拥有跨 connection 的字段转换和时序状态。

## 共同的 transaction pattern

`patterns.InOrderCompletionMonitor` 表达无 transaction ID 的严格 FIFO request/completion：

- request kind 决定合法 completion kind；
- completion 消耗最老 pending token；
- request 到 completion 形成 causal edge；
- resource usage 可以由 InterfaceProtocol 设置容量。

APB 使用容量 1。AHB-Lite 的 canonical address/data pipeline 同样只有一个当前 data-phase obligation。
这只是共享事务形状；cycle observer 仍由各协议定义。

## APB3 / APB4 / APB5

代码位于 `protocol_model/protocols/amba/apb/apb3/`、`apb4/` 和 `apb5/`。三个版本共享同一组
canonical channel 形状：

- `READ`、`WRITE`：Requester → Completer；
- `READ_RESPONSE`、`WRITE_RESPONSE`：Completer → Requester。

APB3 schema 包含 address、write/read data 和规范化的 error response。APB4 分别配置 PPROT 与
PSTRB；read request 的语义字段省略 strobe。APB5 在此基础上可配置：

- `rme_support`：使 PNSE 进入 request 的 `nse`，并要求 PPROT 存在；
- `user_request_width`：PAUSER 映射到 request `auser`；
- `user_data_width`：PWUSER/PRUSER 映射到 write request/read response；
- `user_response_width`：PBUSER 映射到 read/write response；
- `wakeup_signal`：在 cycle observer 中检查 sampled hold 规则；PWAKEUP 保持为 observation-level control。

APB5 parity 属于可选 check profile。当前 `Apb5CheckType` 提供 `NONE`，可执行 profile 的观察范围止于
上述 phase 和 optional user/wakeup 字段。

每个版本的 `Apb3/4/5ObservationSession` 都使用私有 `ApbPhaseObservationSession`，直接表达 APB 的
SETUP/ACCESS phase：

```text
PSEL=1, PENABLE=0                    final PSEL=1, PENABLE=1, PREADY=1
          │ SETUP                                      │ ACCESS completion
          ▼                                            ▼
       READ/WRITE ───────── pending obligation ─────► typed response
```

公共 phase engine 检查：

- SETUP 固定一拍，下一拍进入 ACCESS；
- ACCESS 可以由 PREADY 拉长；
- address、direction、write data、strobe 和 protection 在等待期间稳定；
- 当前版本/profile 声明 PSTRB 时，read transfer 的 strobe 必须为零；
- PRDATA/PSLVERR 只在完成 ACCESS 时进入 canonical response；
- reset 清除未完成 transfer。

APB5 额外检查已配置 optional pin 是否进入 semantic identity，以及 PWAKEUP 与 PSEL 重叠后在
sampled PREADY 之前保持 high。这是离散采样可判定的 hold 规则；glitch-free 这类边沿之间属性需要
更细的 pin adapter 或时序观察。

generic AddressSpace attachment 会从具体 schema 派生可编码的 request attributes。对 APB5 response user
sideband，当前 reference completer 输出零；requester 的 `AccessResult` 投影当前覆盖 data、response 和通用
访问结果。InterfaceProtocol 仍保留 response user 字段的 schema 与 identity。

## AHB-Lite 与 AHB5

基线代码位于 `protocol_model/protocols/amba/ahb/ahb_lite/`。AHB-Lite 单-manager 接口作为 interface
transaction core；interconnect VirtualDut/SystemProtocol 组合 decoder、多个 Subordinate 的 response mux
以及 multi-manager arbitration。

canonical event kinds 为：

- `READ`、`WRITE`：address/control phase；
- `WRITE_DATA`：独立 manager → subordinate data phase；
- `READ_RESPONSE`、`WRITE_RESPONSE`：subordinate data-phase completion。

独立 `WRITE_DATA` 原样表达 address B 与 transfer A data phase 的重叠，并将后一个 cycle 的 HWDATA
关联到正确的 transfer。

```text
edge n:       address A accepted             → READ/WRITE(A)
edge n+1:     data A completes + address B    → response/data(A), READ/WRITE(B)
```

`AhbObservationSession` 当前检查：

- active address phase 只在 HREADY high 时接受；
- HREADY low 延长当前 data phase 和下一 active address offer；
- active address/control 与当前 write data 在 wait state 中保持稳定；
- ERROR 使用两拍 response：第一拍 HRESP=ERROR/HREADY low，下一拍 HRESP=ERROR/HREADY high；
- IDLE/BUSY 不生成 data-transfer request；
- reset 时 HTRANS 为 IDLE，normalized HREADY 为 high。

`AhbBurstMonitor` 当前覆盖 SINGLE、INCR、WRAP/INCR 4/8/16：NONSEQ 开始、SEQ address progression、
wrap boundary、burst 内 direction/control stability、alignment 和 1KB decode boundary。

`protocol_model/protocols/amba/ahb/ahb5/` 从同一 transaction core 派生 Issue C 的 interface payload：

- `extended_memory_types` 选择 7-bit HPROT；
- `secure_transfers` 增加 HNONSEC 对应字段；
- `write_strobes` 增加 HWSTRB。它表达 sparse write byte attributes，并接受非活动 byte lane 上的 strobe
  以及全零取值；
- `exclusive_transfers` 增加 HEXCL/HMASTER/HEXOKAY，并检查 single-beat shape 与 response signaling；
- 三组 User width 分别控制 HAUSER、HWUSER/HRUSER 与 HBUSER。

Exclusive Access Monitor 观察相关地址访问，用于判定外部写冲突是否使 Exclusive Write 成功。AHB5 parity
需要 raw check-signal observation，当前尚处于后续实现范围。sampled-cycle observer 当前绑定 AHB-Lite
基线；AHB5 optional field 的 wait-state stability 随后加入对应 observation profile。

## 规范依据

- [Arm IHI 0024E](https://documentation-service.arm.com/static/63fe2c1356ea36189d4e79f3)：APB signals、transfer phases 与状态机；
- [Arm IHI 0033C](https://documentation-service.arm.com/static/6141bf0d674a052ae36ca811)：AHB transfer、burst、response 与 data bus。
