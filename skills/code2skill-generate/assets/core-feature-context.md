# Feature Context

Use this file only when the background knowledge is not suitable for inclusion directly in `SKILL.md`.

## User Goal

- What goal this Skill helps the user complete.
- Which adjacent goals are outside this Skill's scope.

## Known Business Information

- The primary steps, branches, and stopping conditions for completing the goal.
- The provenance and purpose of known parameters and their corresponding invocation locations, such as an HTTP interface, RPC service/method, message destination, task entry point, or in-process Service.
- Response fields, receipts, or task IDs that help the agent decide the next step.
- Attachment, authentication, runtime-context, and integration prerequisites proven by source code.

## Available Capabilities

- The purpose and applicable invocation semantics of each Function/MCP tool, such as synchronous request-response, synchronous method invocation, in-process Service, or asynchronous submission.
- When these capabilities may be called, skipped, or composed for the current goal.

## Remaining Unknowns

- Information for which there is no direct evidence in the search scope.
- Information that requires the Consumer Agent to continue reasoning from the actual response, backend feedback, or additional user input.

When multiple Skills share Functions and MCP tools, each Skill keeps the context relevant to its own goal within its own directory. Do not make one Skill depend on another through cross-directory relative paths.
