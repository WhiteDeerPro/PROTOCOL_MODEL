# Analysis

本包只读消费 topology、resolved plan、SystemTrace 或资源快照，派生 address reachability、wait-for graph、
deadlock/livelock witness、coverage 和 boundary refinement 结果。

Analysis 不参与 DUT 执行。wait-for/deadlock 需要 runtime 先提供 blocked reason、held lease 和未完成
obligation；在这些事实形成前，本包保持职责占位而不推断结果。
