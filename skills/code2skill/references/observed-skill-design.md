# Observed Skill design

Generate a portable Agent Skill representing how the existing product uses the extracted capabilities. Follow the Agent Skills directory format and keep `SKILL.md` concise, with detailed Feature Context in references.

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

## Composition, not a rigid transcript

Write conditional guidance such as:

```text
If the user only needs provinces, call the province capability and stop.
If a valid topic code is already present, do not reload topic options.
If the user follows up on a search result, call the detail Tool with its issued ID.
For comparison across regions, repeat the search Tool and normalize the result set.
```

Do not force every user through the complete original screen flow. Preserve the original flow as a safe default and a source-derived example, not the only legal composition.

## Knowledge placement

- Put trigger terms and usage contexts in frontmatter `description`.
- Put essential procedure and decision rules in `SKILL.md`.
- Put detailed Feature Context, field semantics, error catalogs, and examples in `references/`.
- Put deterministic reusable checks in `scripts/`.
- Do not duplicate the same knowledge in several files.

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
