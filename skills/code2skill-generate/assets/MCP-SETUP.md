# Skill Installation and MCP Connection for <feature name>

> This is a vNext template. During generation, replace placeholders with the actual `<feature-id>`, package path, environment variables, and authentication boundaries, then remove this note. Do not write real secrets or private configuration formats of a specific Host.

## Install the Skill

```bash
npx skills add ./generated/code2skill/<feature-id> -a <agent-id> -g -y
```

This command installs only the Skill knowledge files. It does not start or register MCP, inject authentication information, or prove that the Function, MCP, or live business environment is available.

## Start MCP

Use the generated package's absolute path to start the stdio MCP server:

```bash
node <absolute-package-path>/mcp-tool/index.mjs
```

<When the Runtime Profile is not Node/stdio, replace this with the actual startup method proven by `export-profile.json`.>

stdio and Streamable HTTP are standard MCP transports. This template's `node-stdio` Runtime Profile uses local stdio. Use the Consumer Host's Streamable HTTP registration interface only when the package has already been independently deployed as a remote service.

## Host Registration Parameters

Map the following runtime-neutral parameters to an MCP registration method supported by the Consumer Host:

```json
{
  "command": "node",
  "args": ["<absolute-package-path>/mcp-tool/index.mjs"],
  "cwd": "<absolute-package-path>",
  "env": {
    "<SOURCE_PROVEN_VARIABLE>": "<provided-by-deployment>"
  }
}
```

Code2Skill provides only these generic runtime parameters. It does not generate private adapters for chat channels, file reception/download, or a specific platform. Some Hosts wrap these fields in `mcpServers`, but that is a Host configuration convention, not an MCP protocol requirement.

## Environment Variables and Authentication

- `<DRY_RUN_VARIABLE>`: Enters dry-run only when set to `1`; it must not cause external side effects.
- `<SOURCE_PROVEN_VARIABLE>`: <Describe its provenance, purpose, whether it is required, and the sensitive-data boundary that prohibits recording it.>
- When calling business APIs, declare a required base-URL environment variable for every independent service. The deployment Host explicitly injects the runtime address. The Function must not default to a test, staging, or production environment, and must stop before a network request when the base URL is missing.
- Do not expose a business API base URL as a public tool parameter. Environment addresses found in source code may be deployment references but must not become runtime defaults.
- The deployment Host or a supported authentication boundary in the target application injects authentication and user/tenant identity. Do not write tokens, cookies, secrets, or session values into `SKILL.md`, `references/feature-context.md`, a manifest, or example commands.
- The second parameter of every MCP tool handler is a trusted `runtimeContext` provided at runtime. Generated callbacks may only pass `(input, runtimeContext)` unchanged to the corresponding Function. They must not construct identity, Guards, confirmation, session, dispatcher, or protected state from public tool parameters. If the deployment runtime cannot provide the context facilities declared by the Capability, disable that capability or keep it `requires-host-integration`.
- If `consumer-requirements.json` declares `attachment-resolution`, the deployment must provide a generic facility that resolves opaque, Host-authorized references into controlled content or streams. Business upload tools use the resolved result, but this package does not implement message integration, attachment reception, or download adapters. Without that facility, attachment-related capabilities remain `requires-host-integration`.

## Connectivity Validation

1. Confirm that the MCP process can start from an independently copied generated package.
2. Use an MCP client to complete `initialize`.
3. Call `tools/list` and verify that tool names and Schemas match the Canonical Contract.
4. Within a safe mock/test boundary, provide each tool with one successful case that conforms to its output Schema and one structured-error case that enters its handler. The handler uses the reviewed `portable-error-normalizer.mjs`: success directly projects the Function result; failure preserves `code/message/details/retryable`; an unknown write result is never automatically retried. Under `<DRY_RUN_VARIABLE>=1`, cover every write tool and verify the complete policy, original validated input, and `content`/`structuredContent`. Also use a countable dispatcher behavioral test to prove that dry-run and Guard-rejection paths have zero external side effects.
5. Execute live `tools/call` only for capabilities that are authorized and safe in the current deployment, preserving evidence separately for each Capability. A write capability that cannot be called safely remains unverified and must not manipulate production data merely as a probe.

## Status Boundaries

- **Skill installed**: The Host's Skill discovery can find the knowledge files.
- **MCP registered**: The Host has saved the correct command/args/cwd/env configuration.
- **MCP connected**: `initialize` and `tools/list` have succeeded.
- **Behavior verified**: Deterministic tests for the corresponding Capability have passed.
- **Runtime verified**: The corresponding Capability has its own live MCP call evidence.
- **Host verified**: Required authentication, confirmation, session, attachment, or unknown-result capabilities have been checked against `host-profile.json`.
- **Deployed**: A separate delivery action has succeeded.

Report these states separately. Do not infer a later state from an earlier one.
