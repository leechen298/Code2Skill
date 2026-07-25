# `strict-export-v1` 流水线

只有用户明确要求完整证据链、Canonical/Goal Contract、Host compatibility、逐能力验证、live receipt、finalization、manifest、外部 evaluator 或合规审计时，才使用 `strict-export-v1`。不要从“稳定”或“可用”自动推断严格模式。

严格模式保留完整产物、校验器和分阶段流水线，兼容旧包；它不是默认交付。

## Producer 阶段

`skills/code2skill-generate/scripts/run_pipeline.py` 驱动五个阶段：

1. `analyze`：解析授权源码范围、证据和 Canonical Contract。
2. `generate`：从 Canonical Contract 确定性编译 Function/MCP，再派生文档视图。
3. `verify`：只执行离线行为验证。
4. `runtime-verify`：显式 opt-in 的真实环境验证，默认关闭。
5. `finalize`：按证据门控收口并生成最终报告。

```bash
python3 skills/code2skill-generate/scripts/run_pipeline.py init \
  generated/code2skill/<feature-id> \
  --source-map client=/authorized/client-root \
  --source-map service=/authorized/service-root
python3 skills/code2skill-generate/scripts/run_pipeline.py run \
  generated/code2skill/<feature-id>
python3 skills/code2skill-generate/scripts/run_pipeline.py status \
  generated/code2skill/<feature-id>
python3 skills/code2skill-generate/scripts/run_pipeline.py diagnose \
  generated/code2skill/<feature-id>
```

默认只完成 `generated + behavior-verified`：

- `validate_artifacts.py --pre-finalize` 做静态校验；
- `probe_mcp.py --offline` 检查 `initialize`、`tools/list`、协议错误和 dry-run，但不宣称网络隔离；
- `run_vectors.py` 从 Canonical Contract 派生 Function、Goal 和 mock-dispatcher 向量；
- 无法机械证明的动态值、附件、组合和条件谓词保留 `requires-review`。

## 增量与恢复

- `init` 先判定 `fresh`、`migrate` 或 `changed-only`。迁移必须审阅摘要并显式 `--acknowledge-migration`。
- 状态保存在候选包外的 `<feature-id>.producer-state/` sidecar。
- 阶段按输入指纹寻址；输入未变化时不重跑，上游变化只失效相关下游。
- 上游失败时，下游旧结果标记为 `invalidated`，不能继续充当有效证明。
- finalize 保存自身输出 Hash；receipt 或 manifest 被删除、篡改后必须重跑。

耗时基准：

```bash
python3 tests/benchmark_pipeline.py
```

该基准测量合成候选的首次、增量和无变化运行，只覆盖确定性流水线，不包含 Agent 首次阅读源码和编写契约的时间。

## 证据与真实验证

真实读取必须使用 `--enable-runtime-verify` 显式开启，并由仓库固定调用器执行。业务入参来自调用方提供且已脱敏的：

```text
verification/cases/live/<capabilityId>.json
```

缺少用例时保持 `not-run`。真实写能力还必须在同一次命令中逐项使用：

```text
--authorize-write <capabilityId>
```

启用和授权仅对本次调用生效，不写入状态。输入变化后，旧 live 证据和结论在 finalize 前作废。

向量、日志、live pair 和报告保存在 `<state>/verification/`。顺序固定为：

```text
执行 → 持久化 → 计算 Hash → 生成报告 → finalize
```

证据路径解析符号链接后仍必须位于 verification 目录内。Host 验证不进入流水线执行，只作为独立状态报告。

## 预收口校验

```bash
python3 skills/code2skill-generate/scripts/validate_artifacts.py \
  generated/code2skill/<feature-id> \
  --source-map client=/authorized/client-root \
  --source-map service=/authorized/service-root \
  --pre-finalize
```

每个 `sourceId=/绝对路径` 必须与 `source-topology.json` 一一对应。校验器只读取显式映射，不搜索整台机器。

MCP 协议探针：

```bash
python3 skills/code2skill-generate/scripts/probe_mcp.py \
  generated/code2skill/<feature-id> \
  --call /path/to/valid-tool-call.json \
  --error-call /path/to/execution-error-tool-call.json \
  --dry-run-call /path/to/dry-run-tool-call.json
```

探针在独立临时副本检查初始化、Tool discovery、输入拒绝、成功调用、结构化执行错误和写 Tool dry-run。复制后的 MCP 不得依赖源仓库的 `node_modules`。

## Finalization

完成单元、协议和已授权 live 调用后：

```bash
python3 skills/code2skill-generate/scripts/finalize_export.py \
  generated/code2skill/<feature-id> \
  --source-map client=/authorized/client-root \
  --source-map service=/authorized/service-root \
  --verification-report /path/to/executed-checks.json \
  --live-input /path/to/capability-input.json \
  --live-result /path/to/capability-result.json
```

`verification-report` 必须符合 [`verification-report.schema.json`](../skills/code2skill-generate/assets/verification-report.schema.json)：

- 每个 Canonical Capability 和 Workflow 各有一行；
- passed phase 提供实际命令、退出码和证据 SHA-256；
- runtime check 绑定真实 Tool、input hash 和 result hash；
- bypass check 证明 `zeroExternalWrites: true`；
- 未运行的 phase 明确写 `not-run`。

每个 Capability 只有拥有自己的匹配 live pair 才能成为 `runtime-verified`。一次只读调用不能批准整个包；无法安全调用时保持 `requires-review`。

最终校验失败时，finalizer 恢复进入收口前的审计文件，不留下看似批准但无效的 receipt、matrix、approval 或 manifest。

## 状态口径

严格模式分别报告：

- `generated`
- `behavior-verified`
- `runtime-verified`
- `host-verified`
- `deployed`

任何前一状态都不能自动证明后一状态。

运行仓库测试：

```bash
python3 -m unittest discover -s tests -v
```
