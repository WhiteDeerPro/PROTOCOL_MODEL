# Documentation

## 核心

- [架构](architecture.md)：为什么拆分 core、semantics、patterns、protocol、VirtualDut 和 Project；
- [代码地图](code_map.md)：当前真实目录及依赖方向；
- [形式语义](semantics.md)：事件、状态迁移、义务、偏序和三值判定；
- [理论审计](theory_audit.md)：自动机、Petri 网、trace theory、逻辑和范畴论的真实使用程度；
- [验证合同](verification_contract.md)：如何记录规则、mutation、未约束和证据。

## 工作流

- [开发流程](development_workflow.md)：从协议研究到 Project 集成；
- [验证 Projects](verification_projects.md)：生命周期、组件清单、项目内组网和当前 AXI bridge Project；
- [VirtualDut 方法](virtual_dut.md)：source/sink/responder/transform、registry与FPU/C proxy；
- [Roadmap](../ROADMAP.md)：后续实现顺序。

## 协议

- [AXI4 派生](axi4_derivation.md)；
- [AXI4 约束来源审计](axi4_constraint_audit.md)；
- [APB3/APB4 派生](apb_derivation.md)。
