# Code2Skill Documentation

The main README contains only the project positioning, installation entry points, and shortest usage path. Detailed design and operational guidance is organized by purpose:

- [Installation and MCP registration](installation.en.md): install the generation and review Skills, install generated artifacts, register local or remote MCP servers, and distinguish the available states.
- [DeepSeek Harness installation](deepseek-harness.en.md): install all three Code2Skill Skills as a Harness Bundle, including profile, validation, and uninstall boundaries.
- [Generated package structure and design principles](generated-results.en.md): capability boundaries, schemas, responses, attachments, offline validation, and repository privacy boundaries.
- [Runtime-neutral generation design](development/runtime-neutral-generation-v1.md): discover capabilities through real invocation entry points and preserve honest runtime integration boundaries across languages and transports.
- [Workflow-aware generation design](development/workflow-aware-generation-v1.md): recognize business decision boundaries without turning every step into a Tool.
- [Advanced validation](advanced-validation.en.md): optional complete evidence collection, staged validation, state management, and finalization.
- [Models and result evaluation](evaluation.en.md): public generation models and runtime configurations with anonymized business details; main-flow completion, business-semantic accuracy, and composite reference scores.
- [Stable artifact architecture](../skills/code2skill-generate/references/vnext-architecture.md): the complete Contract and derived-view architecture.
- [Documentation contract](../skills/code2skill-generate/references/documentation-contract.md): responsibilities and portability requirements for generated-package documentation written for Chinese business contexts.

Usually, you only need the main README and the installation guide. Continue to the other documents only when developing Code2Skill, diagnosing generated artifacts, or using strict audit mode.
