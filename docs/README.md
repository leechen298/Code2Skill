# Code2Skill 文档

README 只保留项目定位、安装入口和最短使用路径。详细设计与运维说明按用途拆分如下：

- [安装与 MCP 注册](installation.md)：安装生成和审核 Skills、安装生成结果、注册本地或远程 MCP，并区分各个可用状态。
- [生成结果的结构和设计原则](generated-results.md)：能力边界、Schema、响应、附件、离线验证和仓库隐私边界。
- [高级验证流程](advanced-validation.md)：可选的完整证据、分阶段验证、状态管理和 finalization。
- [生成模型与结果评估](evaluation.md)：公开生成模型和运行配置，同时匿名保护业务；分别说明主流程完成度、业务语义精确度及综合参考分。
- [稳定产物架构](../skills/code2skill-generate/references/vnext-architecture.md)：完整 Contract 与派生视图架构。
- [文档契约](../skills/code2skill-generate/references/documentation-contract.md)：生成包文档的职责和可移植性要求。

通常只需要阅读 README 和安装文档。只有开发 Code2Skill、排查生成结果或使用严格审计模式时，才需要继续阅读其他文档。
