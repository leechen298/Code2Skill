# Capability modeling specification

## Definitions

| Concept | Code2Skill definition |
| --- | --- |
| MCP | The protocol through which an Agent host discovers context and invokes external capabilities. |
| MCP Server | A service exposing one or more Tools, Resources, or Prompts. |
| Feature Context | Evidence-backed business knowledge extracted from code: purpose, concepts, fields, states, rules, permissions, failures, and original behavior. It is knowledge, not a fourth MCP primitive. |
| MCP Tool | An independently discoverable and selectable business capability with a stable input/output contract. It may have required preconditions. |
| MCP Resource | Context the application controls and clients may read, such as a dynamic catalog or feature description. |
| Tool handler | The explicit implementation entry point for one public Tool. It may call multiple internal helpers or APIs. |
| Observed Skill | Usage knowledge reconstructed from an existing application flow and grounded in code evidence. |
| Derived Skill | A new composition of existing Context and Tools that is not proven to exist in the source application. |
| Deterministic workflow | Runtime code that enforces ordering, transactionality, safety, or consistency that must not depend on Agent compliance. |

## Governing principle

MCP Tools answer **what can execute**. Feature Context answers **what the capability means**. Skills answer **when and how capabilities can be selected and combined**. The Agent decides the composition for the current user goal. Runtime code enforces rules the Agent must not bypass.

## Capability boundary test

A candidate is a strong Tool when most answers are yes:

1. Does it express a business action or query an Agent can name independently?
2. Can it satisfy a complete partial user goal?
3. Could more than one Skill reuse it?
4. Can its inputs, outputs, failure modes, and side effects form a stable contract?
5. Can mandatory preconditions be checked at runtime?
6. Would exposing it avoid forcing unrelated work?

Split a candidate when it combines independently useful goals, incompatible side effects, unrelated permissions, or optional phases. Merge candidates when separating them exposes unstable implementation detail, creates meaningless intermediate state, or breaks required transactionality.

Co-location is not a merge reason. Two local option catalogs remain separate when callers can ask for either one independently, their values have different business meaning, or they feed different downstream inputs. Do not create aggregate `get_page_options`, `get_form_options`, or similar page-shaped Tools just because the values share a source module or require zero HTTP requests.

## Non-equivalences

Never assume:

- one page equals one Tool;
- one component equals one Tool;
- one function equals one Tool;
- one endpoint or HTTP request equals one Tool;
- a Tool is invalid because it depends on a prior value;
- a static option list must always be a Tool;
- the original client flow is the only valid Tool composition.

One Tool may call several endpoints. One endpoint may support multiple business Tools. Tool boundaries follow business semantics and safe reuse.

Preserve source-level value boundaries after choosing the Tool boundary. Multiple visible controls may populate one authoritative object input, while one visible control may feed several requests. Do not infer Tool input shape from DOM layout alone; trace the client request and authoritative API/schema contract.

## Dependency semantics

“Independently selectable” does not mean “dependency-free.” A detail Tool may require an ID issued by a search Tool; a mutation may require a preview token; a continuation may require a server-issued cursor.

Represent such rules twice when useful:

- describe the dependency in Feature Context and the observed Skill;
- enforce it with schema constraints, signed or opaque values, handler validation, server state, authorization, or a deterministic workflow.

Never rely on prose alone for a non-bypassable rule.

## Origin and confidence

Mark every workflow as `observed` or `derived`. Mark every material claim as:

- `fact`: directly supported by source, tests, schema, or runtime evidence;
- `inference`: reasonable but not explicitly proven;
- `unknown`: required information is absent or contradictory.

Only observed workflows qualify as source-derived Golden baselines. Derived Skills require separate validation.
