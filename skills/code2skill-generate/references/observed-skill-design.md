# Observed Skill design

Generate a portable Agent Skill representing how the existing product uses the extracted capabilities. Follow the Agent Skills directory format and keep `SKILL.md` concise, with detailed Feature Context in `references/feature-context.md`.

The generated Skill is consumed by an Agent Host that may not have the Producer's code-reading, terminal, filesystem, confirmation, session, or attachment capabilities. Write guidance from the declared Goal Contract, Canonical Contract, and Consumer requirements rather than assuming the generation environment remains present.

## Required content

The generated Skill must tell an Agent:

- which user goals trigger it;
- what each available Tool contributes;
- how to collect or derive parameters;
- which calls are optional for which goals;
- which prerequisites cannot be skipped;
- common partial and multi-Tool composition paths;
- how to recover from expected failures;
- how to interpret and present results;
- which safety rules remain runtime-enforced;
- which claims are facts, inferences, or unknowns.
- what information is already known, currently missing, conditionally required, derived, dynamic, or stale;
- which missing values can come from trusted Host context or read-only Tools and which must be asked from the user;
- the completion predicate for each full or partial goal;
- which Host capabilities are required and how the path degrades when they are absent.
- how to distinguish a correctable backend business rejection from input, authorization, network, output-contract, and unknown-write-outcome errors;
- when a source-proven attachment requirement needs a Host-provided attachment, the business upload Tool, and downstream result binding.

## Progressive information collection

Do not require a user to supply every field in the opening request. The Skill should tell the Agent to:

1. infer the intended goal only as far as evidence allows;
2. retain information the user already provided and avoid repeated questions;
3. recompute required fields after each answer or Tool result;
4. prefer safe read capabilities when they can resolve several missing values;
5. ask only for missing information that cannot be acquired safely elsewhere;
6. refresh identity-scoped or time-limited dynamic values when stale;
7. present a concise summary before a protected write when trusted confirmation is available.

If all required information is already present and valid, skip unnecessary questions and lookups. If the user asks only for a catalog, calculation, preview, or other partial result, answer and stop without forcing final submission.

## Composition, not a rigid transcript

Write conditional guidance such as:

```text
If the user only needs provinces, call the province capability and stop.
If a valid topic code is already present, do not reload topic options.
If the user follows up on a search result, call the detail Tool with its issued ID.
For comparison across regions, repeat the search Tool and normalize the result set.
```

Do not force every user through the complete original screen flow. Preserve the original flow as a safe default and a source-derived example, not the only legal composition.

Use the Canonical Contract's capability graph for handoffs and stopping points. A temporary combination not observed in the source is a `derived composition`, not an Observed Skill fact. Contract-compatible read-only composition may be useful, but a new write composition must preserve all confirmation, provenance, attachment, idempotency, and unknown-outcome guards and needs separate verification.

## Knowledge placement

- Put trigger terms and usage contexts in frontmatter `description`.
- Put essential procedure and decision rules in `SKILL.md`.
- Put detailed Feature Context, field semantics, error catalogs, and examples in `references/`.
- Always use `references/feature-context.md` for the generated business background; do not generate `PAGE.md` or assume a route exists.
- Put deterministic reusable checks in `scripts/`.
- Do not duplicate the same knowledge in several files.

Keep installation and execution states separate. The generated package documents the generic Skill installation command `npx skills add ./generated/code2skill/<feature-id> -a <agent-id> -g -y`, but states that it installs only the Skill. `MCP-SETUP.md` separately describes MCP startup, Host registration, environment variables, authentication injection, and connectivity verification.

## Origin

Set `origin: observed` in the Code2Skill manifest and attach evidence for the reconstructed flow. New combinations not present in source code must be marked `derived` and verified separately.

## Quality bar

An observed Skill fails review when it:

- only explains how to call one oversized page-level Tool;
- hides optionality and makes all steps mandatory;
- relies on prose for a non-bypassable constraint;
- treats a Tool's `confirmed: true` argument as proof of Host/user confirmation;
- omits result interpretation or failure recovery;
- presents inferred business rules as source facts;
- copies page implementation details without converting them into Agent-usable knowledge.
- asks for all possible fields before conditions make them necessary;
- repeats a question or lookup when a valid value is already available;
- assumes the Consumer Host can read source code, resolve local paths, confirm writes, or retain session state without a declared capability;
- presents a `derived composition` as if it were observed in the source application.
- tells the Agent that every backend business rejection means the workflow is unusable instead of explaining how to correct information or stop safely;
- assumes that installing the Skill also starts, registers, authenticates, or verifies the MCP server;
- assumes the Skill can receive chat attachments or arbitrary local paths instead of requiring a Host-provided approved attachment and a source-proven business upload capability.
