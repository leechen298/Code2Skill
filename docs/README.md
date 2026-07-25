# Code2Skill 文档

README 只保留项目定位、安装入口和最短使用路径。详细设计与运维说明按用途拆分如下：

- [安装与 MCP 注册](installation.md)：安装 Producer/Review Skills、安装生成包、注册本地或远程 MCP，并区分各个可用状态。
- [`core-export-v1` 产物规范](core-export.md)：默认精简产物、能力边界、Schema、响应、附件、离线验证和仓库隐私边界。
- [`strict-export-v1` 流水线](strict-export.md)：可选严格模式的阶段、状态、证据和 finalization。
- [生成模型与产物评估](evaluation.md)：公开生成模型/运行配置，同时匿名保护业务；分别说明主流程完成度、业务语义精确度及综合参考分。
- [稳定产物架构](../skills/code2skill-generate/references/vnext-architecture.md)：完整 Contract 与派生视图架构。
- [文档契约](../skills/code2skill-generate/references/documentation-contract.md)：生成包文档的职责和可移植性要求。

通常只需要阅读 README 和安装文档。只有开发 Code2Skill、排查生成结果或使用严格审计模式时，才需要继续阅读其他文档。
