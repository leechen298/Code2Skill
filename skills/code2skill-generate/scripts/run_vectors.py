#!/usr/bin/env python3
"""Deterministic offline behavior vectors for Code2Skill candidates.

This is one of the fixed, repository-maintained verification steps of the
Producer pipeline. It never executes candidate-declared commands: it derives
the canonical minimum behavior checks from ``canonical-contract.json`` (via
``contract_model.capability_verification_checks``) and executes what can be
proven mechanically and offline:

- ``valid-input-and-output-contract``: call each Function with a
  schema-derived minimal valid input; assert the success rule, required
  output paths, forbidden output keys, and the derived output schema.
- ``invalid-input-is-rejected``: missing required inputs, an extra key, and a
  wrong-typed value must be rejected.
- ``structured-error-recovery``: rejections carry a structured
  code/message/details/retryable shape (through the candidate's own
  portable error normalizer).
- ``unknown-write-outcome-is-non-retryable`` and
  ``backend-business-error-is-structured``: normalizer assertions for writes.
- ``exact-request-binding-and-success-status``: HTTP capabilities run against
  a mock dispatcher that records requests; the exact method, URL template,
  fixed query, headers, body shape, and accepted statuses are checked against
  the Canonical implementation binding with zero real network calls.
- Goal vectors (``goal-<id>-...``): progressive completion evaluated with
  ``contract_model.evaluate_goal_state`` and schema-derived sample
  information.

Checks that cannot be derived mechanically in this round (dynamic value
freshness, attachment resolution, derived composition, conditional predicate
evaluation, custom declared checkIds) are reported as ``uncovered`` and stay
``requires-review`` instead of being filled by arbitrary commands.

Usage: ``run_vectors.py <candidate> --out <verification-dir>``.
Exit code 0 when every attempted check passed (uncovered checks are reported,
not failures); 1 when any attempted check failed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from contract_model import (
    capability_verification_checks,
    derive_schema_contract,
    evaluate_goal_state,
    json_schema_errors,
)

NODE_DRIVER = r"""
import { readFileSync, writeFileSync } from 'node:fs';

const [jobPath, outPath] = process.argv.slice(2);
const job = JSON.parse(readFileSync(jobPath, 'utf8'));
const candidate = job.candidate;
const functions = await import(`file://${candidate}/function-core/index.mjs`);
const { normalizeToolError } = await import(`file://${candidate}/portable-error-normalizer.mjs`);
const contract = JSON.parse(readFileSync(`${candidate}/canonical-contract.json`, 'utf8'));

const results = [];

function evidenceBase(check) {
  return { checkId: check.checkId, capabilityId: check.capabilityId, kind: check.kind };
}

function outputProblems(data, capability) {
  const problems = [];
  if (data === null || typeof data !== 'object' || Array.isArray(data)) {
    problems.push('result.data must be an object');
    return problems;
  }
  for (const key of capability.successRule.forbiddenOutputKeys || []) {
    if (key in data) problems.push(`forbidden output key present: ${key}`);
  }
  for (const path of capability.successRule.requiredOutputPaths || []) {
    let current = data;
    let missing = false;
    for (const segment of path) {
      if (current && typeof current === 'object' && segment in current) {
        current = current[segment];
      } else {
        missing = true;
        break;
      }
    }
    if (missing || current === null || current === undefined) {
      problems.push(`required output path missing: ${path.join('.')}`);
    }
  }
  return problems;
}

function runValidCall(check, capability, fn) {
  const captured = [];
  const context = {
    dispatch: async (url, options) => {
      captured.push({ url, options: options || {} });
      const step = (check.mockResponses || [])[captured.length - 1];
      if (!step) throw new Error(`unexpected dispatch #${captured.length}`);
      return step;
    },
    resolvedAttachments: check.resolvedAttachments || {},
  };
  return fn(check.validInput, context).then((result) => {
    const evidence = evidenceBase(check);
    evidence.status = 'passed';
    evidence.output = result && typeof result === 'object' ? result.data ?? null : null;
    evidence.resultStatus = result && typeof result === 'object' ? result.status ?? null : null;
    const problems = [];
    if (!result || typeof result !== 'object') problems.push('Function must return a result object');
    else {
      const expectedStatuses = check.expectedStatuses || ['success'];
      if (!expectedStatuses.includes(result.status)) {
        problems.push(`result.status must be one of ${JSON.stringify(expectedStatuses)}, got ${JSON.stringify(result.status)}`);
      }
      problems.push(...outputProblems(result.data, capability));
    }
    evidence.capturedRequests = captured;
    if (problems.length) {
      evidence.status = 'failed';
      evidence.detail = problems.join('; ');
    } else {
      evidence.detail = 'valid input accepted; output contract satisfied';
    }
    return evidence;
  }).catch((error) => {
    const evidence = evidenceBase(check);
    evidence.status = 'failed';
    evidence.detail = `valid input was rejected: ${error && error.message ? error.message : error}`;
    evidence.capturedRequests = captured;
    return evidence;
  });
}

async function runInvalidCall(check, capability, fn) {
  const evidence = evidenceBase(check);
  const failures = [];
  for (const badInput of check.invalidInputs) {
    let rejected = false;
    let detail = null;
    try {
      await fn(badInput, { dispatch: async () => { throw new Error('dispatch must not run'); } });
    } catch (error) {
      rejected = true;
      detail = error && error.message ? error.message : String(error);
    }
    if (!rejected) {
      failures.push(`invalid input was accepted: ${JSON.stringify(badInput)}`);
    }
  }
  evidence.status = failures.length ? 'failed' : 'passed';
  evidence.detail = failures.length
    ? failures.join('; ')
    : `${check.invalidInputs.length} invalid input case(s) rejected`;
  return evidence;
}

async function runErrorShape(check, capability, fn) {
  const evidence = evidenceBase(check);
  let thrown = null;
  try {
    await fn(check.invalidInputs[0], { dispatch: async () => { throw new Error('dispatch must not run'); } });
  } catch (error) {
    thrown = error;
  }
  if (!thrown) {
    evidence.status = 'failed';
    evidence.detail = 'invalid input was accepted; no structured error to recover';
    return evidence;
  }
  const normalized = normalizeToolError(thrown, check.operationPolicy);
  const problems = [];
  if (typeof normalized.code !== 'string' || !normalized.code) problems.push('normalized error needs a code');
  if (typeof normalized.message !== 'string' || !normalized.message) problems.push('normalized error needs a message');
  if (typeof normalized.details !== 'object' || normalized.details === null) problems.push('normalized error needs details');
  if (typeof normalized.retryable !== 'boolean') problems.push('normalized error needs a retryable flag');
  evidence.status = problems.length ? 'failed' : 'passed';
  evidence.detail = problems.length ? problems.join('; ') : `structured error preserved (${normalized.code})`;
  evidence.normalized = normalized;
  return evidence;
}

function runNormalizerCase(check, expectation) {
  const evidence = evidenceBase(check);
  const normalized = normalizeToolError(check.error, check.operationPolicy);
  const problems = [];
  if (normalized.code !== expectation.code) problems.push(`code must be ${expectation.code}, got ${normalized.code}`);
  if (normalized.retryable !== expectation.retryable) problems.push(`retryable must be ${expectation.retryable}, got ${normalized.retryable}`);
  if (expectation.outcomeKnown !== undefined && normalized.details.outcomeKnown !== expectation.outcomeKnown) {
    problems.push(`details.outcomeKnown must be ${expectation.outcomeKnown}`);
  }
  evidence.status = problems.length ? 'failed' : 'passed';
  evidence.detail = problems.length ? problems.join('; ') : `normalized as ${normalized.code}`;
  evidence.normalized = normalized;
  return evidence;
}

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function runHttpBinding(check, capability, fn) {
  const captured = [];
  const context = {
    dispatch: async (url, options) => {
      captured.push({ url, options: options || {} });
      const step = (check.mockResponses || [])[captured.length - 1];
      if (!step) throw new Error(`unexpected dispatch #${captured.length}`);
      return step;
    },
    resolvedAttachments: check.resolvedAttachments || {},
  };
  return fn(check.validInput, context).then((result) => {
    const evidence = evidenceBase(check);
    evidence.capturedRequests = captured;
    const problems = [];
    const expectedSteps = check.expectedSteps || [];
    if (captured.length !== expectedSteps.length) {
      problems.push(`expected ${expectedSteps.length} request step(s), captured ${captured.length}`);
    }
    expectedSteps.forEach((step, index) => {
      const actual = captured[index];
      if (!actual) return;
      const options = actual.options || {};
      if (step.method && String(options.method || '').toUpperCase() !== step.method.toUpperCase()) {
        problems.push(`step ${index} method must be ${step.method}, got ${options.method}`);
      }
      if (step.url && actual.url !== step.url) {
        problems.push(`step ${index} url must be ${step.url}, got ${actual.url}`);
      }
      const expectedQuery = step.query || {};
      if (!deepEqual(options.query || {}, expectedQuery)) {
        problems.push(`step ${index} query must exactly equal ${JSON.stringify(expectedQuery)}, got ${JSON.stringify(options.query || {})}`);
      }
      const actualHeaders = {};
      for (const [name, value] of Object.entries(options.headers || {})) {
        actualHeaders[name.toLowerCase()] = value;
      }
      for (const [name, value] of Object.entries(step.headers || {})) {
        if (actualHeaders[name.toLowerCase()] !== value) {
          problems.push(`step ${index} header ${name} must be ${JSON.stringify(value)}, got ${JSON.stringify(actualHeaders[name.toLowerCase()])}`);
        }
      }
      if (step.body !== undefined && !deepEqual(options.body, step.body)) {
        problems.push(`step ${index} body must equal ${JSON.stringify(step.body)}, got ${JSON.stringify(options.body)}`);
      }
      for (const name of Object.keys(step.multipart || {})) {
        if (!(name in (options.multipart || {}))) {
          problems.push(`step ${index} multipart field ${name} is missing`);
        }
      }
    });
    const output = result && typeof result === 'object' ? result.data ?? null : null;
    const expectedStatuses = check.expectedStatuses || ['success'];
    if (!result || typeof result !== 'object' || !expectedStatuses.includes(result.status)) {
      problems.push(`mock success response must map to an accepted status in ${JSON.stringify(expectedStatuses)}, got ${result && result.status}`);
    } else {
      problems.push(...outputProblems(output, capability));
    }
    evidence.output = output;
    evidence.resultStatus = result && typeof result === 'object' ? result.status ?? null : null;
    evidence.status = problems.length ? 'failed' : 'passed';
    evidence.detail = problems.length ? problems.join('; ') : 'exact request binding and success status preserved';
    return evidence;
  }).catch((error) => {
    const evidence = evidenceBase(check);
    evidence.status = 'failed';
    evidence.detail = `http binding vector failed: ${error && error.message ? error.message : error}`;
    evidence.capturedRequests = captured;
    return evidence;
  });
}

async function runHttpRejection(check, capability, fn) {
  const evidence = evidenceBase(check);
  evidence.checkId = `${check.checkId}--non-accepted-status`;
  evidence.kind = 'http-rejection';
  const captured = [];
  const context = {
    dispatch: async (url, options) => {
      captured.push({ url, options: options || {} });
      const step = (check.rejectionResponses || [])[captured.length - 1];
      if (!step) throw new Error(`unexpected dispatch #${captured.length}`);
      return step;
    },
    resolvedAttachments: check.resolvedAttachments || {},
  };
  try {
    await fn(check.validInput, context);
  } catch (error) {
    const normalized = normalizeToolError(error, check.operationPolicy);
    const problems = [];
    if (captured.length !== 1) problems.push(`rejection must stop after the first failing step, captured ${captured.length} dispatch(es)`);
    if (typeof normalized.code !== 'string' || !normalized.code) problems.push('rejection must produce a structured error code');
    if (normalized.retryable !== false) problems.push('rejection must not be retryable');
    evidence.status = problems.length ? 'failed' : 'passed';
    evidence.detail = problems.length ? problems.join('; ') : `non-accepted status rejected as ${normalized.code} after ${captured.length} dispatch(es)`;
    evidence.normalized = normalized;
    evidence.capturedRequests = captured;
    return evidence;
  }
  evidence.status = 'failed';
  evidence.detail = 'non-accepted status was silently accepted as success';
  evidence.capturedRequests = captured;
  return evidence;
}

for (const check of job.checks) {
  const capability = contract.capabilities.find((item) => item.capabilityId === check.capabilityId);
  if (!capability) {
    results.push({ ...evidenceBase(check), status: 'failed', detail: 'unknown capability' });
    continue;
  }
  const fn = functions[capability.functionExport];
  if (typeof fn !== 'function') {
    results.push({ ...evidenceBase(check), status: 'failed', detail: `missing Function export ${capability.functionExport}` });
    continue;
  }
  if (check.kind === 'valid-call') {
    results.push(await runValidCall(check, capability, fn));
  } else if (check.kind === 'invalid-call') {
    results.push(await runInvalidCall(check, capability, fn));
  } else if (check.kind === 'error-shape') {
    results.push(await runErrorShape(check, capability, fn));
  } else if (check.kind === 'unknown-outcome') {
    results.push(runNormalizerCase(check, { code: 'UNKNOWN_DISPATCH_OUTCOME', retryable: false }));
  } else if (check.kind === 'backend-error') {
    results.push(runNormalizerCase(check, { code: check.error.code, retryable: false, outcomeKnown: true }));
  } else if (check.kind === 'http-binding') {
    results.push(await runHttpBinding(check, capability, fn));
    results.push(await runHttpRejection(check, capability, fn));
  } else {
    results.push({ ...evidenceBase(check), status: 'failed', detail: `unknown vector kind ${check.kind}` });
  }
}

writeFileSync(outPath, JSON.stringify({ checks: results }, null, 2));
"""


def sample_value(schema: dict[str, Any] | None) -> Any:
    """Derive one minimal valid sample value from a JSON Schema."""
    if not isinstance(schema, dict) or not schema:
        return "synthetic-value"
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    for union in ("anyOf", "oneOf"):
        if isinstance(schema.get(union), list):
            non_null = [
                item for item in schema[union]
                if not (isinstance(item, dict) and item.get("type") == "null")
            ]
            return sample_value(non_null[0] if non_null else schema[union][0])
    expected = schema.get("type")
    if isinstance(expected, list):
        expected = next((item for item in expected if item != "null"), "string")
    if expected == "boolean":
        return True
    if expected in {"number", "integer"}:
        minimum = schema.get("minimum", 1)
        return minimum if isinstance(minimum, (int, float)) else 1
    if expected == "array":
        item = sample_value(schema.get("items"))
        min_items = schema.get("minItems", 1)
        return [item] * max(1, min_items) if isinstance(min_items, int) else [item]
    if expected == "object":
        properties = schema.get("properties", {}) if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required", []) if isinstance(schema.get("required"), list) else []
        return {
            name: sample_value(properties.get(name))
            for name in required
            if isinstance(name, str)
        }
    if schema.get("format") == "uri":
        return "https://synthetic.example/resource"
    min_length = schema.get("minLength", 1)
    return "synthetic-value" if not isinstance(min_length, int) or min_length <= 15 else "s" * min_length


def sample_arguments(capability: dict[str, Any]) -> dict[str, Any]:
    """Minimal valid Tool arguments from the Canonical input declarations."""
    arguments: dict[str, Any] = {}
    for item in capability.get("inputs", []):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        required = item.get("required") is True and not item.get("requiredWhen")
        if required:
            arguments[item["name"]] = sample_value(
                item.get("schema") if isinstance(item.get("schema"), dict) else {"type": item.get("type")}
            )
    return arguments


def invalid_argument_cases(capability: dict[str, Any]) -> list[dict[str, Any]]:
    valid = sample_arguments(capability)
    cases: list[dict[str, Any]] = []
    required_names = [
        item["name"]
        for item in capability.get("inputs", [])
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item.get("required") is True
        and not item.get("requiredWhen")
    ]
    for name in required_names[:3]:
        case = dict(valid)
        case.pop(name, None)
        cases.append(case)
    cases.append({**valid, "__code2skill_unexpected_argument__": True})
    if required_names:
        wrong = dict(valid)
        first = required_names[0]
        wrong[first] = {"unexpected": "object"}
        cases.append(wrong)
    return cases


def resolve_binding_value(
    source: dict[str, Any],
    arguments: dict[str, Any],
    mock_responses: dict[str, dict[str, Any]],
    resolved_attachments: dict[str, Any],
) -> Any:
    kind = source.get("kind")
    if kind == "input":
        return arguments.get(source.get("inputName"))
    if kind == "prior_response":
        step_id = source.get("stepId")
        data = (mock_responses.get(step_id) or {}).get("data")
        for segment in source.get("path", []):
            data = data.get(segment) if isinstance(data, dict) else None
        return data
    if kind == "host_resolved_attachment":
        return resolved_attachments.get(source.get("inputName"))
    return None


def expected_http_steps(
    capability: dict[str, Any],
    arguments: dict[str, Any],
    origin: str,
    output_data_sample: Any,
) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None, list[dict[str, Any]] | None, str | None]:
    """Full expected requests + mock responses from the Canonical binding.

    Returns (expected_steps, mock_responses, rejection_responses, error).
    Anything not precisely verifiable in this round (URL-path bindings,
    non-flat query/header/multipart/body paths) yields an explicit error so
    the check is reported uncovered instead of loosely verified.
    """
    implementation = capability.get("implementation", {})
    steps = implementation.get("steps", []) if isinstance(implementation, dict) else []
    resolved_attachments = {
        item["name"]: "synthetic-resolved-attachment-content"
        for item in capability.get("inputs", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    mock_responses: dict[str, dict[str, Any]] = {}
    ordered_responses: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        success_codes = step.get("successStatusCodes") or [200]
        mock_data = output_data_sample if index == len(steps) - 1 else {}
        response = {"status": success_codes[0], "data": mock_data}
        mock_responses[step.get("stepId")] = response
        ordered_responses.append(response)
    for step in steps:
        query: dict[str, Any] = {}
        headers: dict[str, Any] = {
            str(name).lower(): value
            for name, value in (step.get("headers", {}) or {}).items()
        }
        body: dict[str, Any] | None = None
        multipart: dict[str, Any] = {}
        for binding in step.get("bindings", []):
            if not isinstance(binding, dict):
                continue
            location = binding.get("location")
            path = binding.get("path") if isinstance(binding.get("path"), list) else []
            source = binding.get("source", {}) if isinstance(binding.get("source"), dict) else {}
            value = resolve_binding_value(source, arguments, mock_responses, resolved_attachments)
            if source.get("kind") == "input" and source.get("inputName") not in arguments:
                # An optional input that is not supplied is legitimately
                # omitted from the request rather than sent as null.
                continue
            if location == "query":
                if len(path) != 1:
                    return None, None, None, f"non-flat query binding path {path} is not verifiable in this round"
                query[path[0]] = value
            elif location == "header":
                if len(path) != 1:
                    return None, None, None, f"non-flat header binding path {path} is not verifiable in this round"
                headers[str(path[0]).lower()] = value
            elif location == "body":
                if len(path) != 1:
                    return None, None, None, f"nested body binding path {path} is not verifiable in this round"
                if body is None:
                    body = {}
                body[path[0]] = value
            elif location == "multipart":
                if len(path) != 1:
                    return None, None, None, f"non-flat multipart binding path {path} is not verifiable in this round"
                multipart[path[0]] = value
            elif location == "path":
                return None, None, None, "URL path bindings are not verifiable in this round"
            elif location is not None:
                return None, None, None, f"unsupported binding location {location}"
        expected.append(
            {
                "method": step.get("method"),
                "url": step.get("url"),
                "query": query,
                "headers": headers,
                "body": body,
                "multipart": multipart,
                "successStatusCodes": step.get("successStatusCodes") or [200],
            }
        )
    rejection_responses: list[dict[str, Any]] = []
    if steps:
        first_codes = steps[0].get("successStatusCodes") or [200]
        rejected_status = 500 if 500 not in first_codes else 418
        rejection_responses.append({"status": rejected_status, "data": {"error": "synthetic rejection"}})
    return expected, ordered_responses, rejection_responses, None


def output_schema_for(capability: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for output in capability.get("outputs", []):
        if not isinstance(output, dict):
            continue
        path = output.get("path")
        if not isinstance(path, list) or len(path) != 1 or not isinstance(path[0], str):
            continue
        properties[path[0]] = (
            output.get("schema") if isinstance(output.get("schema"), dict) else {"type": output.get("type")}
        )
        required.append(path[0])
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
    }


def goal_state(value: Any) -> dict[str, Any]:
    return {"__goalState": True, "value": value, "fresh": True, "acquiredNow": True}


def goal_sample_information(goal: dict[str, Any]) -> dict[str, Any]:
    information: dict[str, Any] = {}
    for need in goal.get("informationNeeds", []):
        if not isinstance(need, dict) or not isinstance(need.get("informationId"), str):
            continue
        information[need["informationId"]] = goal_state(
            sample_value(need.get("schema") if isinstance(need.get("schema"), dict) else {"type": need.get("type")})
        )
    return information


def run_goal_vector(
    goal: dict[str, Any], kind: str
) -> tuple[str, str]:
    """Evaluate one progressive-completion vector; returns (status, detail)."""
    goal_id = goal.get("goalId")
    needs = [
        item
        for item in goal.get("informationNeeds", [])
        if isinstance(item, dict) and isinstance(item.get("informationId"), str)
    ]
    need_ids = [item["informationId"] for item in needs]
    samples = goal_sample_information(goal)
    if kind == "different-information-orders-converge":
        empty = evaluate_goal_state(goal, {})
        if empty.get("complete"):
            return "failed", "empty goal state must not be complete"
        completed_a = evaluate_goal_state(goal, dict(samples))
        completed_b = evaluate_goal_state(goal, dict(reversed(list(samples.items()))))
        if completed_a != completed_b or not completed_a.get("complete"):
            return "failed", "different information orders must converge to the same completion"
        for need_id in need_ids:
            partial = evaluate_goal_state(goal, {need_id: samples[need_id]})
            expected_missing = sorted(item for item in need_ids if item != need_id)
            if sorted(partial.get("missingInformationIds", [])) != expected_missing:
                return (
                    "failed",
                    f"partial state with only {need_id} must miss exactly {expected_missing}",
                )
        return "passed", "all information orders converge to the same completion"
    if kind == "all-known-skips-questions-and-tools":
        state = evaluate_goal_state(goal, dict(samples))
        problems = []
        if not state.get("complete"):
            problems.append("all-known state must complete")
        if state.get("askInformationIds"):
            problems.append("no questions may be asked when everything is known")
        if state.get("acquisitionCapabilityIds"):
            problems.append("no capability calls may be requested when everything is known")
        return ("failed", "; ".join(problems)) if problems else (
            "passed",
            "all-known state skips questions and capability calls",
        )
    if kind == "asks-only-currently-missing":
        state = evaluate_goal_state(goal, {})
        user_needs = sorted(
            item["informationId"]
            for item in needs
            if any(
                isinstance(strategy, dict) and strategy.get("kind") == "user"
                for strategy in item.get("satisfiedBy", [])
            )
        )
        capability_providers = sorted(
            {
                strategy.get("capabilityId")
                for item in needs
                for strategy in item.get("satisfiedBy", [])
                if isinstance(strategy, dict) and strategy.get("kind") == "capability"
            }
            - {None}
        )
        problems = []
        if sorted(state.get("missingInformationIds", [])) != sorted(need_ids):
            problems.append(f"empty state must miss exactly {sorted(need_ids)}")
        if sorted(state.get("askInformationIds", [])) != user_needs:
            problems.append(f"only user-provided needs may be asked: {user_needs}")
        if sorted(state.get("acquisitionCapabilityIds", [])) != capability_providers:
            problems.append(
                f"only capability-provided needs may trigger capabilities: {capability_providers}"
            )
        return ("failed", "; ".join(problems)) if problems else (
            "passed",
            "only currently missing information is requested",
        )
    return "uncovered", f"no mechanical goal vector for {kind}"


def build_function_checks(
    contract: dict[str, Any], origin: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the node-driver job and the uncovered-check list."""
    node_checks: list[dict[str, Any]] = []
    uncovered: list[dict[str, Any]] = []
    output_data_schemas = {
        item.get("capabilityId"): (item.get("outputSchema") or {}).get("properties", {}).get("data")
        for item in derive_schema_contract(contract).get("capabilities", [])
        if isinstance(item, dict)
    }
    for capability in contract.get("capabilities", []):
        if not isinstance(capability, dict) or not isinstance(capability.get("capabilityId"), str):
            continue
        capability_id = capability["capabilityId"]
        expected = capability_verification_checks(capability, contract)
        arguments = sample_arguments(capability)
        expected_steps, mock_responses, rejection_responses, binding_error = expected_http_steps(
            capability,
            arguments,
            origin,
            sample_value(output_data_schemas.get(capability_id)),
        )
        implementation = capability.get("implementation", {})
        output_step = next(
            (
                step
                for step in implementation.get("steps", [])
                if isinstance(step, dict)
                and step.get("stepId") == implementation.get("outputStepId")
            ),
            None,
        )
        expected_statuses = (
            output_step.get("successStatusCodes", [200])
            if isinstance(output_step, dict)
            else ["success"]
        )
        resolved_attachments = {
            item["name"]: "synthetic-resolved-attachment-content"
            for item in capability.get("inputs", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        for item in expected:
            check_id = item.get("checkId") if isinstance(item, dict) else item
            phase = item.get("phase", "behavior") if isinstance(item, dict) else "behavior"
            if phase != "behavior":
                continue
            base = {"checkId": check_id, "capabilityId": capability_id}
            if check_id == "valid-input-and-output-contract":
                node_checks.append({
                    **base,
                    "kind": "valid-call",
                    "validInput": arguments,
                    "mockResponses": mock_responses,
                    "resolvedAttachments": resolved_attachments,
                    "expectedStatuses": expected_statuses,
                })
            elif check_id == "invalid-input-is-rejected":
                node_checks.append({
                    **base,
                    "kind": "invalid-call",
                    "invalidInputs": invalid_argument_cases(capability),
                })
            elif check_id == "structured-error-recovery":
                node_checks.append({
                    **base,
                    "kind": "error-shape",
                    "invalidInputs": invalid_argument_cases(capability),
                    "operationPolicy": capability.get("operationPolicy", {}),
                })
            elif check_id == "unknown-write-outcome-is-non-retryable":
                node_checks.append({
                    **base,
                    "kind": "unknown-outcome",
                    "error": {"message": "synthetic timeout after dispatch"},
                    "operationPolicy": capability.get("operationPolicy", {}),
                })
            elif check_id == "backend-business-error-is-structured":
                node_checks.append({
                    **base,
                    "kind": "backend-error",
                    "error": {
                        "code": "SYNTHETIC_BACKEND_REJECTION",
                        "message": "synthetic backend business rejection",
                        "details": {"field": "synthetic"},
                        "outcomeKnown": True,
                    },
                    "operationPolicy": capability.get("operationPolicy", {}),
                })
            elif check_id == "exact-request-binding-and-success-status":
                if binding_error is not None:
                    uncovered.append({**base, "reason": binding_error})
                else:
                    node_checks.append({
                        **base,
                        "kind": "http-binding",
                        "validInput": arguments,
                        "expectedSteps": expected_steps,
                        "mockResponses": mock_responses,
                        "rejectionResponses": rejection_responses,
                        "resolvedAttachments": resolved_attachments,
                        "operationPolicy": capability.get("operationPolicy", {}),
                        "expectedStatuses": expected_statuses,
                    })
            elif check_id.startswith("goal-"):
                continue  # handled by the python goal vectors
            else:
                uncovered.append({
                    **base,
                    "reason": "no mechanical offline vector for this checkId in this round",
                })
    return node_checks, uncovered


def build_goal_checks(contract: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for capability in contract.get("capabilities", []):
        if not isinstance(capability, dict) or not isinstance(capability.get("capabilityId"), str):
            continue
        for item in capability_verification_checks(capability, contract):
            check_id = item.get("checkId") if isinstance(item, dict) else item
            if not isinstance(check_id, str) or not check_id.startswith("goal-"):
                continue
            key = (capability["capabilityId"], check_id)
            if key in seen:
                continue
            seen.add(key)
            checks.append({
                "checkId": check_id,
                "capabilityId": capability["capabilityId"],
            })
    return checks


def goal_kind(check_id: str) -> str | None:
    for suffix in (
        "different-information-orders-converge",
        "all-known-skips-questions-and-tools",
        "asks-only-currently-missing",
    ):
        if check_id.endswith(suffix):
            return suffix
    return None


def run(
    candidate: Path, out_dir: Path, *, node: str = "node", origin: str = "https://synthetic.invalid"
) -> dict[str, Any]:
    contract_path = candidate / "canonical-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = out_dir / "vector-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "candidate": str(candidate),
        "contractId": contract.get("contractId"),
        "checks": [],
        "uncovered": [],
    }

    node_checks, uncovered = build_function_checks(contract, origin)
    report["uncovered"].extend(uncovered)
    results: list[dict[str, Any]] = []
    if node_checks:
        job_path = out_dir / "vector-job.json"
        driver_path = out_dir / "vector-driver.mjs"
        output_path = out_dir / "vector-output.json"
        job_path.write_text(
            json.dumps({"candidate": str(candidate), "checks": node_checks}, ensure_ascii=False),
            encoding="utf-8",
        )
        driver_path.write_text(NODE_DRIVER, encoding="utf-8")
        completed = subprocess.run(
            [node, str(driver_path), str(job_path), str(output_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"vector driver failed: {completed.stderr.strip()[:400] or completed.stdout.strip()[:400]}"
            )
        results.extend(json.loads(output_path.read_text(encoding="utf-8"))["checks"])

    goals = {
        goal.get("goalId"): goal
        for goal in contract.get("goals", [])
        if isinstance(goal, dict) and isinstance(goal.get("goalId"), str)
    }
    for check in build_goal_checks(contract):
        check_id = check["checkId"]
        goal_id = next(
            (gid for gid in goals if check_id.startswith(f"goal-{gid}-")), None
        )
        kind = goal_kind(check_id)
        if goal_id is None or kind is None:
            report["uncovered"].append({
                "checkId": check_id,
                "capabilityId": check["capabilityId"],
                "reason": "no mechanical goal vector for this checkId in this round",
            })
            continue
        status, detail = run_goal_vector(goals[goal_id], kind)
        results.append({
            "checkId": check_id,
            "capabilityId": check["capabilityId"],
            "kind": f"goal-{kind}",
            "status": status,
            "detail": detail,
        })

    # Validate successful-call outputs against the exact derived output
    # schema (types, enums, arrays, closed objects) — presence checks alone
    # would let wrong-typed data fake a pass.
    output_schemas = {
        item.get("capabilityId"): item.get("outputSchema")
        for item in derive_schema_contract(contract).get("capabilities", [])
        if isinstance(item, dict)
    }
    for result in results:
        if result.get("status") != "passed":
            continue
        if result.get("kind") not in {"valid-call", "http-binding"}:
            continue
        output_schema = output_schemas.get(result.get("capabilityId"))
        if not isinstance(output_schema, dict):
            continue
        schema_errors = json_schema_errors(
            {"status": result.get("resultStatus"), "data": result.get("output")},
            output_schema,
        )
        if schema_errors:
            result["status"] = "failed"
            result["detail"] = "output schema violation: " + "; ".join(schema_errors[:5])

    for result in results:
        scope = result.get("capabilityId") or "global"
        evidence_name = f"behavior--{scope}--{result['checkId']}.json".replace("/", "_")
        evidence_path = evidence_dir / evidence_name
        evidence_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report["checks"].append({
            "checkId": result["checkId"],
            "capabilityId": result.get("capabilityId"),
            "phase": "behavior",
            "status": result["status"],
            "detail": result.get("detail"),
            "evidence": f"vector-evidence/{evidence_name}",
        })
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="verification output directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidate = args.candidate.resolve()
    try:
        report = run(candidate, args.out.resolve())
    except (OSError, json.JSONDecodeError, RuntimeError) as error:
        print(f"ERROR run_vectors: {error}", file=sys.stderr)
        return 1
    (args.out.resolve() / "vector-summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    failed = [check for check in report["checks"] if check["status"] == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
