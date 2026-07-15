# AHB-Lite 与 APB phased LinkProtocol

AHB-Lite 和 APB 都是点到点可判定的 `LinkProtocol`，但 pin/cycle phase 不同，也不是同一 schema 上的
继承关系：

```text
AHB-Lite LinkProtocol ──┐
                        ├── AHB→APB bridge VirtualDut ──► two independent links
APB LinkProtocol ───────┘
```

bridge 需要保存 AHB request、驱动 APB SETUP/ACCESS，并把 APB completion 转回 AHB data phase。
这些跨 link 状态属于具体 bridge module；两端协议本身不包含字段转换或时序转换。

## 共同的 transaction pattern

`patterns.InOrderCompletionMonitor` 表达无 transaction ID 的严格 FIFO request/completion：

- request kind 决定合法 completion kind；
- completion 消耗最老 pending token；
- request 到 completion 形成 causal edge；
- resource usage 可以由 LinkProtocol 设置容量。

APB 使用容量 1。AHB-Lite 的 canonical address/data pipeline 同样只有一个当前 data-phase obligation。
这只是共享事务形状；cycle observer 仍由各协议定义。

## APB3 / APB4 / APB5

代码位于 `protocol_model/link/amba/apb/apb3/`、`apb4/` 和 `apb5/`。三个版本共享同一组
canonical channel 形状：

- `READ`、`WRITE`：Requester → Completer；
- `READ_RESPONSE`、`WRITE_RESPONSE`：Completer → Requester。

APB3 schema 包含 address、write/read data 和规范化的 error response。APB4 可独立配置 PPROT 与
PSTRB，不再用一个开关绑定两者；read request 不携带 strobe。APB5 在此基础上可配置：

- `rme_support`：使 PNSE 进入 request 的 `nse`，并要求 PPROT 存在；
- `user_request_width`：PAUSER 映射到 request `auser`；
- `user_data_width`：PWUSER/PRUSER 映射到 write request/read response；
- `user_response_width`：PBUSER 映射到 read/write response；
- `wakeup_signal`：在 cycle observer 中检查 sampled hold 规则，不把 PWAKEUP 当成地址访问字段。

APB5 parity 属于可选 check profile。当前 `Apb5CheckType` 只提供 `NONE`，因此当前 APB5 可执行 profile 不声明
对 parity pin 进行了观察或校验。

每个版本的 `Apb3/4/5ObservationSession` 都使用私有 `ApbPhaseObservationSession`，但不把 APB 当作
ready-valid：

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
- 只在当前版本/profile 宣布 PSTRB 时检查 read transfer 为零；
- PRDATA/PSLVERR 只在完成 ACCESS 时进入 canonical response；
- reset 清除未完成 transfer。

APB5 额外检查已配置 optional pin 是否进入 semantic identity，以及 PWAKEUP 与 PSEL 重叠后在
sampled PREADY 之前不下降。这是离散采样可判定的 hold 规则；glitch-free 这类边沿之间属性需要
更细的 pin adapter 或时序观察。

generic AddressSpace attachment 会从具体 schema 派生可编码的 request attributes。对 APB5 response user
sideband，当前 reference completer 输出零，requester 不投影到 `AccessResult`；这是 integration 的当前行为，
不是 LinkProtocol 删除了这些字段。

## AHB-Lite 与 AHB5

基线代码位于 `protocol_model/link/amba/ahb/ahb_lite/`。当前选择 AHB-Lite 单-manager 接口作为 link
transaction core。decoder、多个
Subordinate 的 response mux，以及 multi-manager arbitration 属于 interconnect VirtualDut/SystemProtocol。

canonical channels 为：

- `READ`、`WRITE`：address/control phase；
- `WRITE_DATA`：独立 manager → subordinate data phase；
- `READ_RESPONSE`、`WRITE_RESPONSE`：subordinate data-phase completion。

保留独立 `WRITE_DATA` 很重要：它使 address B 与 transfer A data phase 的重叠能够被原样表达，而不把
后一个 cycle 的 HWDATA 塞进前一个 address event。

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

`protocol_model/link/amba/ahb/ahb5/` 从同一 transaction core 派生 Issue C 的 link payload：

- `extended_memory_types` 选择 7-bit HPROT；
- `secure_transfers` 增加 HNONSEC 对应字段；
- `write_strobes` 增加 HWSTRB。它表达 sparse write byte attributes；非活动 byte lane 上的 strobe 不由
  LinkProtocol 拒绝，全零也允许；
- `exclusive_transfers` 增加 HEXCL/HMASTER/HEXOKAY，并检查 single-beat shape 与 response signaling；
- 三组 User width 分别控制 HAUSER、HWUSER/HRUSER 与 HBUSER。

外部写冲突是否使 Exclusive Write 成功，需要能观察相关地址访问的 Exclusive Access Monitor；它不由单条
AHB link 猜测。AHB5 parity 尚未实现，因为它需要 raw check-signal observation。当前 sampled-cycle observer
只绑定 AHB-Lite 基线；AHB5 optional field 的 wait-state stability 属于后续 observation 实现范围。

## 规范依据

- [Arm IHI 0024E](https://documentation-service.arm.com/static/63fe2c1356ea36189d4e79f3)：APB signals、transfer phases 与状态机；
- [Arm IHI 0033C](https://documentation-service.arm.com/static/6141bf0d674a052ae36ca811)：AHB transfer、burst、response 与 data bus。
