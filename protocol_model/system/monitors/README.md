# Monitors

本包负责消费多个 connection 上的 SystemEvent，维护 request-owner/response-return、coherence aggregation、
ordering、progress 等 reference ledger，并产生 system-scope verdict。

Monitor 检查实际模块共同形成的行为；它不代替 crossbar/Home/endpoint backend 发出协议事件，也不成为真实
directory 或 owner table 的第二份可变实现。
