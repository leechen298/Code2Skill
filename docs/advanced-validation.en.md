# Advanced Validation Workflow

Use the advanced validation workflow only when the user explicitly requests a complete evidence chain, Canonical/Goal Contracts, host compatibility, per-capability validation, live receipts, finalization, manifests, an external evaluator, or a compliance audit. Internally, the tooling identifies this compatibility format as `strict-export-v1`. Do not infer that it is required merely from words such as “stable” or “usable.”

Strict mode preserves the complete artifacts, validators, and staged pipeline for compatibility with legacy packages. It is not the default delivery mode.

The current `strict-export-v1` compatibility contract still emits `zh-CN` Agent-facing documentation. English and Chinese default-generation templates are both available, but they do not make strict-mode output bilingual. Treat English strict output as a separate future compatibility upgrade rather than weakening or bypassing the existing documentation validators.

## Producer Stages

`skills/code2skill-generate/scripts/run_pipeline.py` drives five stages:

1. `analyze`: Parse the authorized source scope, evidence, and Canonical Contract.
2. `generate`: Deterministically compile Functions and MCP from the Canonical Contract, then derive documentation views.
3. `verify`: Perform offline behavioral validation only.
4. `runtime-verify`: Perform explicitly opted-in live-environment validation; disabled by default.
5. `finalize`: Apply evidence gates and produce the final report.

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

By default, the pipeline completes only `generated + behavior-verified`:

- `validate_artifacts.py --pre-finalize` performs static validation.
- `probe_mcp.py --offline` checks `initialize`, `tools/list`, protocol errors, and dry-run behavior, but does not claim network isolation.
- `run_vectors.py` derives Function, Goal, and mock-dispatcher vectors from the Canonical Contract.
- Dynamic values, attachments, combinations, and conditional predicates that cannot be proven mechanically remain `requires-review`.

## Incremental Runs and Recovery

- `init` first determines whether the run is `fresh`, `migrate`, or `changed-only`. A migration requires reviewing its summary and explicitly passing `--acknowledge-migration`.
- State is stored outside the candidate package in a `<feature-id>.producer-state/` sidecar.
- Stages are addressed by input fingerprint. A stage is not rerun when its input is unchanged; upstream changes invalidate only the relevant downstream stages.
- When an upstream stage fails, previous downstream results are marked `invalidated` and cannot continue to serve as valid evidence.
- Finalization saves a hash of its own output. If a receipt or manifest is deleted or modified, the stage must be rerun.

Run the timing benchmark with:

```bash
python3 tests/benchmark_pipeline.py
```

The benchmark measures first, incremental, and no-change runs against a synthetic candidate. It covers only the deterministic pipeline and excludes the time an agent spends initially reading source code and writing contracts.

## Evidence and Live Validation

Live reads must be explicitly enabled with `--enable-runtime-verify` and executed by a repository-defined runner. Business inputs come from caller-provided, sanitized files at:

```text
verification/cases/live/<capabilityId>.json
```

When a case is missing, its status remains `not-run`. Each live write capability must also be individually authorized in the same command with:

```text
--authorize-write <capabilityId>
```

Enabling and authorizing apply only to the current invocation and are not written to state. When inputs change, previous live evidence and conclusions are invalidated before finalization.

Vectors, logs, live pairs, and reports are stored under `<state>/verification/`. The order is fixed:

```text
execute → persist → compute hash → generate report → finalize
```

After symbolic links are resolved, evidence paths must still remain inside the verification directory. Host validation is not executed by the pipeline and is reported only as an independent status.

## Pre-finalization Validation

```bash
python3 skills/code2skill-generate/scripts/validate_artifacts.py \
  generated/code2skill/<feature-id> \
  --source-map client=/authorized/client-root \
  --source-map service=/authorized/service-root \
  --pre-finalize
```

Every `sourceId=/absolute/path` must correspond one-to-one with `source-topology.json`. The validator reads only explicit mappings and does not search the entire machine.

MCP protocol probe:

```bash
python3 skills/code2skill-generate/scripts/probe_mcp.py \
  generated/code2skill/<feature-id> \
  --call /path/to/valid-tool-call.json \
  --error-call /path/to/execution-error-tool-call.json \
  --dry-run-call /path/to/dry-run-tool-call.json
```

In an isolated temporary copy, the probe checks initialization, tool discovery, input rejection, successful calls, structured execution errors, and write-tool dry runs. The copied MCP server must not depend on the source repository's `node_modules`.

## Finalization

After unit, protocol, and authorized live calls have completed:

```bash
python3 skills/code2skill-generate/scripts/finalize_export.py \
  generated/code2skill/<feature-id> \
  --source-map client=/authorized/client-root \
  --source-map service=/authorized/service-root \
  --verification-report /path/to/executed-checks.json \
  --live-input /path/to/capability-input.json \
  --live-result /path/to/capability-result.json
```

`verification-report` must conform to [`verification-report.schema.json`](../skills/code2skill-generate/assets/verification-report.schema.json):

- Include one row for every Canonical Capability and Workflow.
- For a passed phase, provide the actual command, exit code, and evidence SHA-256.
- Bind each runtime check to the actual tool, input hash, and result hash.
- The bypass check must prove `zeroExternalWrites: true`.
- Explicitly mark every phase that was not executed as `not-run`.

When a human-readable summary is useful before finalization, use the English [legacy human verification summary template](../skills/code2skill-generate/assets/verification-report.md). It does not replace the JSON execution evidence above.

Each capability can become `runtime-verified` only when it has its own matching live pair. One read-only call cannot approve an entire package. When a capability cannot be called safely, it remains `requires-review`.

If final validation fails, the finalizer restores the audit files that existed before finalization. It does not leave behind receipts, matrices, approvals, or manifests that appear approved but are invalid.

## Status Vocabulary

Strict mode reports these states separately:

- `generated`
- `behavior-verified`
- `runtime-verified`
- `host-verified`
- `deployed`

No earlier state automatically proves a later state.

Run the repository tests with:

```bash
python3 -m unittest discover -s tests -v
```
