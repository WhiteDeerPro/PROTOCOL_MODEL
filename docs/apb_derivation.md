# APB3 / APB4 Derivation

规范基线：Arm AMBA APB Protocol Specification，IHI 0024C/E。

APB是同步、非流水协议，每次传输至少两个周期：

```text
IDLE → SETUP → ACCESS(wait*) → COMPLETE
```

## 版本差异

| 版本 | 行为 |
|---|---|
| APB3 | 在基础APB上增加 PREADY wait state 与 PSLVERR error response |
| APB4 | 继承APB3，并增加 PSTRB sparse write 与 PPROT protection attribute |

## 通用自动机

`ClockedTwoPhaseTransfer` 不知道APB字段名，只通过回调获得 selected、enabled、ready、
request/completion projection 与 reset predicate。APB3/APB4都实例化该组件。

已实现：

- SETUP时 `PSEL=1, PENABLE=0`；
- 下一周期进入 `PSEL=1, PENABLE=1` 的ACCESS；
- `PREADY=0` 可以无限延长ACCESS；
- 请求字段从SETUP保持到完成；
- 完成条件为 `PSEL && PENABLE && PREADY`；
- PSLVERR只在完成采样点进入canonical transfer；
- PRESETn低返回IDLE；
- APB4 PSTRB每字节一位，且读传输期间全零；
- APB4 PPROT为稳定的3-bit请求属性。

有意不约束：PREADY延迟、PRDATA内容、PSLVERR产生原因和PPROT的系统权限效果。

当前边界：单个PSEL/单个completer；尚无多外设decoder、register/RAM虚拟DUT和APB bridge。
