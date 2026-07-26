# Protocol Model brand mark

本目录保存人工维护的项目标志。`protocol-model-mark.svg` 是当前唯一维护源，不由 scenario 或 artifact
runner 生成。

## 概念

标志只表达一条稳定关系：

```text
interface boundary → transformed path / typed event → interface boundary
```

两条深色竖块表示明确的接口边界。灰青路径只发生一次阶梯变化，表示通信事实经过模型后被重新组织；中央
粉色方块表示一笔 typed atomic event。图形不指定方向、channel 数量或具体协议，也不把 bridge、fabric、
crossbar 和 NoC 的分叉塞入标志。

## 文件

- `protocol-model-mark.svg`：唯一标志，透明背景；
- `protocol-model-mark.png`：从同一 SVG 渲染的便于查看版本；
- `studies/expressive-connector-mark.svg` / `studies/expressive-connector-mark.png`：从“插头找到匹配插座后
  成为可工作关系”的第一认知抽取出的静态 expressive 候选；
- `studies/` 中其余文件：早期人工与生成式探索，只保存设计过程。

## 初稿配色

| 用途 | 色值 |
|---|---|
| 轮廓与接口边界 | `#17191B` |
| 通信路径 | `#6F8583` |
| typed atomic event | `#B5747A` |

颜色用于增强路径和事件的层次；接口边界仍承担主要轮廓。

当前标志仍可复审，但后续修订直接改进这一构图，不按场景派生不同 Logo。
