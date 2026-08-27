# MCP Installation and Runtime

> This template uses the `node-stdio` runtime profile as an example. The current implementation of the default `core-export-v1` package format is `node-stdio`. When the target stack is not Node/stdio, use the dependency installation and MCP server startup commands for that language, while preserving the separate states for installation, registration, connectivity, validation, and deployment. During generation, replace placeholders with the actual package path, agent ID, environment variables, and dry-run variable; remove example entries when no corresponding environment variable exists. Do not leave placeholders or real credentials in delivered files.

## Install the Skill

```bash
npx skills add <bundle-path> --skill '*' --agent <agent-id> --global --yes
```

This step installs only the Agent Skill. It does not install dependencies, start or register the MCP server, or inject authentication information.

## Install MCP Dependencies

Current `node-stdio` profile example. When the generated package includes `package-lock.json`:

```bash
cd <absolute-bundle-path>
npm ci
```

Use `npm install` when there is no lockfile.

## Local stdio MCP

Current `node-stdio` profile example. The default generated package uses the standard MCP stdio transport, with the Consumer Host starting a local child process:

```bash
node <absolute-bundle-path>/mcp-tool/index.mjs
```

Map the following runtime-neutral launch parameters to the Consumer Host's MCP registration interface:

```json
{
  "command": "node",
  "args": ["<absolute-bundle-path>/mcp-tool/index.mjs"],
  "cwd": "<absolute-bundle-path>",
  "env": {
    "<SOURCE_PROVEN_VARIABLE>": "<provided-by-deployment>"
  }
}
```

This is a portable launch description, not a private configuration file for a particular Host. Use absolute paths. Write only MCP protocol messages to stdout and ordinary logs to stderr.

## Remote MCP

Register a Streamable HTTP endpoint through the Consumer Host only when this package has already been independently deployed as a remote service. Code2Skill does not deploy remote gateways or present Host conventions such as `mcpServers` as MCP protocol requirements.

## Environment Variables and Authentication

- List only environment variables proven by source code or the Runtime Profile.
- When calling business APIs, list a clearly named required base-URL variable for every independent service, such as `CODE2SKILL_<FEATURE>_<SERVICE>_BASE_URL`. The Consumer Host explicitly injects the actual address. The Function must not default to test, staging, or production environments.
- Environment addresses found in source code are deployment references only, not runtime defaults. When a required base URL is missing, stop before the network request; do not silently fall back.
- Do not expose the business API base URL to the agent as a tool parameter. The agent supplies only business invocation parameters.
- The runtime injects authentication and user/tenant identity through environment variables or an existing credential mechanism.
- Do not write tokens, cookies, secrets, session values, or real credentials into the Skill, source code, example commands, or this file.
- Dry-run variable: `<DRY_RUN_VARIABLE>`; it takes effect only when set to `1`.

## Unmet Prerequisites

When the target capability lacks a safely callable client, runtime context, dependencies, or a safe entry point, the package must honestly mark it as `requires-host-integration`. Do not use documentation in `MCP-SETUP.md`, the Skill, or the Function to pretend that the capability is runnable. In that case, `MCP-SETUP.md` must explicitly list:

- Missing runtime facilities, such as the original application process, dependency-injection container, language-specific SDK, message/task Broker connection, or attachment-resolution service.
- Integration work the deployer must supply.
- The fact that the capability cannot currently undergo automatic runtime validation and that the Consumer Host or target system must complete the integration before a live call.

## Offline Checks

Current `node-stdio` profile example:

```bash
<DRY_RUN_VARIABLE>=1 npm test
```

After registration, use an MCP client to complete `initialize`, `tools/list`, and a representative safe mock/dry-run `tools/call`. Offline tests use `.invalid`, a local mock, or an injected fake base URL, and verify that no network request occurs when the required base URL is missing. Live business interfaces are not called by default. Call them only with explicit user authorization; write interfaces must never be called automatically as probes.

## Status Boundaries

- **Skill installed**: The agent can discover the Skill.
- **Dependencies installed**: The package's runtime dependencies are present.
- **MCP registered**: The Host has saved the launch parameters or remote URL.
- **MCP connected**: `initialize` and `tools/list` have succeeded.
- **Offline behavior verified**: Mock/dry-run tests have passed.
- **Live business behavior verified**: Authorized live calls have passed.
- **Deployed**: A separate deployment action has completed.

Report these states separately. None can be inferred from another.
