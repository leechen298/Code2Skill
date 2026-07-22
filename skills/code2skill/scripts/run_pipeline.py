#!/usr/bin/env python3
"""Staged Producer pipeline for the Code2Skill first-round generation flow.

This driver turns the previous single-pass export into five explicit stages:

1. ``analyze``        - source scope, evidence resolution, Canonical Contract checks
2. ``generate``       - deterministic compilation (compile_artifacts.py:
                        Canonical Contract -> Function core and MCP adapter)
                        plus derivation of the contract views
3. ``verify``         - offline behavior verification only, executed by fixed
                        repository-maintained scripts: strict artifact
                        validation, the offline MCP protocol probe, and
                        deterministic Function/Goal vectors derived from the
                        Canonical Contract (scripts/run_vectors.py). The
                        pipeline never executes candidate-declared commands and
                        never requires business credentials.
4. ``runtime-verify`` - opt-in live verification against an authorized
                        environment (``--enable-runtime-verify``) through the
                        repository-fixed live caller. Write capabilities
                        additionally require explicit per-capability
                        authorization (``--authorize-write <capabilityId>``).
                        Both apply to a single invocation only and are never
                        persisted into state.
5. ``finalize``       - evidence-gated finalization plus an honest stage report.
                        Finalization re-verifies every relied-upon record
                        (scoped per capability/workflow), refuses missing,
                        temporary, or modified evidence, and stores hashes of
                        its own outputs so damaged receipts force a re-run.

Run state lives in a Producer sidecar directory (default
``<candidate>.producer-state/``) outside the portable candidate package.
Completed stages are content-addressed: a stage re-runs only when its own
inputs changed, interrupted runs resume safely, unchanged stages are never
repeated, and a failed upstream stage marks downstream completed stages as
``invalidated`` instead of letting stale proof stand. Verification outputs,
logs, live evidence, and reports persist under ``<state-dir>/verification/``;
they never depend on temporary directories, and evidence is hashed only after
it is persisted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contract_model import (
    ContractError,
    capability_verification_checks,
    derive_schema_contract,
    json_schema_errors,
    validate_canonical_contract,
    validate_source_topology,
)
from finalize_export import digest_json
import run_vectors
from validate_artifacts import Diagnostics, parse_source_maps, validate
# Reused so the analyze stage resolves evidence locators with the exact same
# rules as the strict validator instead of drifting into a second copy.
from validate_vnext import _validate_source_topology_and_evidence

PIPELINE_VERSION = "producer-pipeline/v1"
STATE_SCHEMA = "producer-run-state/v1"
CHECKS_SCHEMA = "producer-checks/v1"

STAGES = ("analyze", "generate", "verify", "runtime-verify", "finalize")
STAGE_STATUSES = {"pending", "running", "completed", "failed", "invalidated"}

AUTHORING_INPUTS = (
    "source-topology.json",
    "canonical-contract.json",
    "export-profile.json",
    "host-profile.json",
)
HAND_AUTHORED_FILES = (
    "mcp-tool/runtime.mjs",
    "portable-workflow-guard.mjs",
    "SKILL.md",
    "MCP.zh-CN.md",
    "MCP-SETUP.md",
    "references/feature-context.md",
)
# Finalizer outputs are excluded from input fingerprints: they are produced by
# the finalize stage itself and would otherwise re-invalidate verify forever.
FINALIZATION_REL_PATHS = {
    "function-core/validation-receipt.json",
    "preflight-report.json",
    "approval-audit.json",
    "live-verification.json",
    "verification-matrix.json",
    "export-manifest.json",
}
TREE_EXCLUDE_NAMES = {".git", ".DS_Store", "__pycache__", "node_modules"}

SCRIPT_DIR = Path(__file__).resolve().parent
STANDARD_CHECK_STATIC = "pipeline:static-artifact-validation"
STANDARD_CHECK_PROBE = "pipeline:mcp-protocol-offline"
STANDARD_CHECK_VECTORS = "pipeline:offline-behavior-vectors"
STANDARD_CHECK_IDS = {
    STANDARD_CHECK_STATIC,
    STANDARD_CHECK_PROBE,
    STANDARD_CHECK_VECTORS,
}


class PipelineError(ValueError):
    """Raised for operator-facing pipeline usage errors."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, location: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PipelineError(f"{location}: required file is missing: {path}")
    except (OSError, UnicodeError) as error:
        raise PipelineError(f"{location}: cannot read {path}: {error}")
    except json.JSONDecodeError as error:
        raise PipelineError(f"{location}: invalid JSON in {path}: {error}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def iter_tree_files(
    root: Path,
    *,
    exclude_rel_paths: set[str] | None = None,
    exclude_prefixes: tuple[Path, ...] = (),
) -> list[tuple[str, Path]]:
    """Deterministically list files under root without following dir symlinks."""
    exclude_rel_paths = exclude_rel_paths or set()
    if not root.is_dir():
        return []
    resolved_root = root.resolve()
    entries: list[tuple[str, Path]] = []
    for current, dir_names, file_names in os.walk(resolved_root, followlinks=False):
        dir_names[:] = sorted(
            name
            for name in dir_names
            if name not in TREE_EXCLUDE_NAMES
            and not any(
                (Path(current) / name).resolve().is_relative_to(prefix)
                for prefix in exclude_prefixes
            )
        )
        for name in sorted(file_names):
            if name in TREE_EXCLUDE_NAMES:
                continue
            path = Path(current) / name
            relative = path.relative_to(resolved_root).as_posix()
            if relative in exclude_rel_paths:
                continue
            if any(path.resolve().is_relative_to(prefix) for prefix in exclude_prefixes):
                continue
            entries.append((relative, path))
    return sorted(entries)


def tree_digest(
    root: Path,
    *,
    exclude_rel_paths: set[str] | None = None,
    exclude_prefixes: tuple[Path, ...] = (),
) -> str:
    if not root.is_dir():
        return "missing"
    lines = []
    for relative, path in iter_tree_files(
        root, exclude_rel_paths=exclude_rel_paths, exclude_prefixes=exclude_prefixes
    ):
        lines.append(f"{relative}\0{sha256_file(path)}")
    return sha256_bytes("\n".join(lines).encode("utf-8"))


def file_digest_or_missing(path: Path) -> str:
    return sha256_file(path) if path.is_file() else "missing"


MARKER_PATTERN = re.compile(
    r"<!-- code2skill-capability-contract-sha256:[a-f0-9]{64} -->"
)
MARKER_NORMALIZED = "<!-- code2skill-capability-contract-sha256:normalized -->"


def doc_digest_or_missing(path: Path) -> str:
    """Hash a document with its derived SHA-256 marker normalized, so a
    mechanical marker refresh never counts as an authoring change."""
    if not path.is_file():
        return "missing"
    text = path.read_text(encoding="utf-8")
    return sha256_bytes(MARKER_PATTERN.sub(MARKER_NORMALIZED, text).encode("utf-8"))


def default_state_dir(candidate: Path) -> Path:
    return candidate.parent / f"{candidate.name}.producer-state"


def empty_stage_entry() -> dict[str, Any]:
    return {
        "status": "pending",
        "inputFingerprint": None,
        "fingerprintInputs": [],
        "lastAction": None,
        "skipReason": None,
        "invalidatedReason": None,
        "startedAt": None,
        "endedAt": None,
        "durationMs": None,
        "command": None,
        "errorSummary": None,
        "outputHashes": None,
        "runs": 0,
    }


def default_state(candidate: Path, state_dir: Path) -> dict[str, Any]:
    return {
        "schemaVersion": STATE_SCHEMA,
        "pipelineVersion": PIPELINE_VERSION,
        "featureId": candidate.name,
        "candidateDir": str(candidate),
        "stateDir": str(state_dir),
        "mode": None,
        "modeSummary": {},
        "migrationAcknowledged": False,
        "sourceMaps": {},
        # Informational only: live authorizations apply per invocation and are
        # never read back to justify a later run.
        "runtimeVerify": {},
        "stages": {name: empty_stage_entry() for name in STAGES},
        "capabilities": {},
        "lastFinalization": None,
        "createdAt": utc_now(),
        "updatedAt": utc_now(),
    }


def load_state(state_dir: Path) -> dict[str, Any] | None:
    path = state_dir / "run-state.json"
    if not path.is_file():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schemaVersion") != STATE_SCHEMA:
        raise PipelineError(
            f"run-state.json schemaVersion must equal {STATE_SCHEMA}; "
            "remove the state directory or migrate it explicitly"
        )
    # Crash recovery: a stage still marked running means the previous producer
    # exited mid-stage. Mark it failed so the resume re-executes it safely.
    for entry in state.get("stages", {}).values():
        if entry.get("status") == "running":
            entry["status"] = "failed"
            entry["lastAction"] = None
            entry["errorSummary"] = (
                "interrupted: the producer exited before this stage completed; "
                "it is safe to resume"
            )
    return state


def save_state(state_dir: Path, state: dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    state["updatedAt"] = utc_now()
    target = state_dir / "run-state.json"
    temporary = state_dir / ".run-state.json.tmp"
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def verification_layout(state_dir: Path) -> dict[str, Path]:
    verification = state_dir / "verification"
    return {
        "root": verification,
        "cases": verification / "cases",
        "dry_run_cases": verification / "cases" / "dry-run",
        "vectors": verification / "vectors",
        "results": verification / "results",
        "logs": verification / "logs",
        "live": verification / "live",
        "reports": verification / "reports",
    }


# ---------------------------------------------------------------------------
# Input fingerprints
# ---------------------------------------------------------------------------


def stage_fingerprint_inputs(
    stage: str,
    candidate: Path,
    state_dir: Path,
    state: dict[str, Any],
    runtime_auth: set[str] | None = None,
) -> list[list[str]]:
    """Return sorted [label, digest] inputs for one stage.

    A completed stage is re-executed only when this fingerprint changes, which
    makes resumes safe and invalidates exactly the affected downstream stages.
    """
    layout = verification_layout(state_dir)
    entries: list[list[str]] = []

    def add_file(label: str, path: Path) -> None:
        entries.append([label, file_digest_or_missing(path)])

    def add_tree(label: str, root: Path, **kwargs: Any) -> None:
        entries.append([label, tree_digest(root, **kwargs)])

    add_file("code:run_pipeline.py", SCRIPT_DIR / "run_pipeline.py")
    if stage == "analyze":
        for name in AUTHORING_INPUTS:
            add_file(f"candidate:{name}", candidate / name)
        for source_id in sorted(state.get("sourceMaps", {})):
            root = Path(state["sourceMaps"][source_id])
            add_tree(
                f"source-tree:{source_id}",
                root,
                exclude_prefixes=(candidate.resolve(), state_dir.resolve()),
            )
        add_file("code:contract_model.py", SCRIPT_DIR / "contract_model.py")
        add_file("code:validate_vnext.py", SCRIPT_DIR / "validate_vnext.py")
    elif stage == "generate":
        for name in AUTHORING_INPUTS:
            add_file(f"candidate:{name}", candidate / name)
        add_file("candidate:authoring/tool-docs.json", candidate / "authoring" / "tool-docs.json")
        for name in HAND_AUTHORED_FILES:
            if name in {"SKILL.md", "MCP.zh-CN.md", "references/feature-context.md"}:
                entries.append([f"candidate:{name}", doc_digest_or_missing(candidate / name)])
            else:
                add_file(f"candidate:{name}", candidate / name)
        add_file("code:compile_artifacts.py", SCRIPT_DIR / "compile_artifacts.py")
        add_file("code:derive_artifacts.py", SCRIPT_DIR / "derive_artifacts.py")
        add_file("code:contract_model.py", SCRIPT_DIR / "contract_model.py")
    elif stage in {"verify", "runtime-verify"}:
        add_tree(
            "candidate-tree",
            candidate,
            exclude_rel_paths=FINALIZATION_REL_PATHS,
        )
        for script in (
            "validate_artifacts.py",
            "validate_vnext.py",
            "probe_mcp.py",
            "run_vectors.py",
            "contract_model.py",
            "derive_artifacts.py",
        ):
            add_file(f"code:{script}", SCRIPT_DIR / script)
        if stage == "runtime-verify":
            # Fingerprint the per-invocation authorization so an enabled run
            # or a changed write authorization re-executes the stage.
            entries.append(["runtime-verify:enabled", "true"])
            entries.append(
                [
                    "runtime-verify:authorizedWrites",
                    digest_json(sorted(runtime_auth or set())),
                ]
            )
            # Fingerprint the per-invocation authorization so an enabled run
            # or a changed write authorization re-executes the stage.
            entries.append(["runtime-verify:enabled", "true"])
            entries.append(
                [
                    "runtime-verify:authorizedWrites",
                    digest_json(sorted(runtime_auth or set())),
                ]
            )
    elif stage == "finalize":
        add_tree(
            "candidate-tree",
            candidate,
            exclude_rel_paths=FINALIZATION_REL_PATHS,
        )
        add_tree("verification:results", layout["results"])
        add_tree(
            "verification:live",
            layout["live"],
            # The placeholder pairs are written by the finalize stage itself;
            # they must not re-invalidate it on the next run.
            exclude_rel_paths={
                "no-runtime-verification.input.json",
                "no-runtime-verification.result.json",
            },
        )
        for script in (
            "finalize_export.py",
            "validate_artifacts.py",
            "validate_vnext.py",
            "contract_model.py",
        ):
            add_file(f"code:{script}", SCRIPT_DIR / script)
    else:  # pragma: no cover - guarded by callers
        raise PipelineError(f"unknown stage: {stage}")
    return sorted(entries)


def fingerprint_of(inputs: list[list[str]]) -> str:
    return sha256_bytes(
        json.dumps(inputs, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def capability_hashes(candidate: Path) -> dict[str, str]:
    contract_path = candidate / "canonical-contract.json"
    if not contract_path.is_file():
        return {}
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(contract, dict):
        return {}
    return {
        item["capabilityId"]: digest_json(item)
        for item in contract.get("capabilities", [])
        if isinstance(item, dict) and isinstance(item.get("capabilityId"), str)
    }


# ---------------------------------------------------------------------------
# Mode detection and init
# ---------------------------------------------------------------------------

LEGACY_MARKERS = ("capability-bundle.json", "PAGE.md", "workflow.json")


def declared_core_profile(candidate: Path) -> str | None:
    package_path = candidate / "package.json"
    if not package_path.is_file():
        return None
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(package, dict):
        return None
    code2skill = package.get("code2skill")
    return code2skill.get("profile") if isinstance(code2skill, dict) else None


def detect_mode(candidate: Path) -> str:
    if not candidate.is_dir():
        return "fresh"
    if (candidate / "canonical-contract.json").is_file():
        return "changed-only"
    if any((candidate / marker).is_file() for marker in LEGACY_MARKERS):
        return "migrate"
    profile_path = candidate / "export-profile.json"
    if profile_path.is_file():
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            profile = None
        if isinstance(profile, dict):
            return "migrate"
    if any(candidate.iterdir()):
        # Unrecognized content: never silently build over it.
        return "migrate"
    return "fresh"


def build_mode_summary(
    candidate: Path, state: dict[str, Any], mode: str
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "mode": mode,
        "candidateDir": str(candidate),
        "detectedAt": utc_now(),
    }
    if mode == "migrate":
        legacy_files = []
        for path in sorted(candidate.rglob("*")):
            if path.is_file() and ".git" not in path.parts:
                legacy_files.append(
                    {
                        "relativePath": path.relative_to(candidate).as_posix(),
                        "sha256": sha256_file(path),
                    }
                )
        summary["legacyFiles"] = legacy_files
        summary["requiredActions"] = [
            "author vNext inputs: source-topology.json, canonical-contract.json, host-profile.json",
            "keep or remove legacy-only files deliberately (PAGE.md, workflow.json); the pipeline never deletes them",
            "run `run_pipeline.py init --acknowledge-migration` after reviewing this summary, then `run_pipeline.py run`",
        ]
        summary["note"] = (
            "migrate mode never modifies or removes legacy artifacts silently; "
            "this summary is recorded before any change"
        )
    elif mode == "changed-only":
        previous = state.get("capabilities", {})
        current = capability_hashes(candidate)
        summary["capabilities"] = {
            "added": sorted(set(current) - set(previous)),
            "removed": sorted(set(previous) - set(current)),
            "changed": sorted(
                key
                for key in set(current) & set(previous)
                if current[key] != previous[key]
            ),
            "unchanged": sorted(
                key
                for key in set(current) & set(previous)
                if current[key] == previous[key]
            ),
        }
        summary["note"] = (
            "the capability-level diff is informational; stage input fingerprints "
            "decide conservatively which stages actually re-run"
        )
    else:
        summary["nextSteps"] = [
            "author source-topology.json, canonical-contract.json, export-profile.json, host-profile.json",
            "author function-core, mcp-tool and documentation artifacts",
            "run `run_pipeline.py run` to execute analyze -> generate -> verify -> finalize",
        ]
    return summary


def parse_source_map_args(values: list[str]) -> dict[str, str]:
    diagnostics = Diagnostics()
    parsed = parse_source_maps(values, diagnostics)
    if diagnostics.errors:
        raise PipelineError("; ".join(diagnostics.errors))
    return {source_id: str(path) for source_id, path in parsed.items()}


def cmd_init(args: argparse.Namespace) -> int:
    candidate = args.candidate.resolve()
    state_dir = (
        args.state_dir.resolve() if args.state_dir else default_state_dir(candidate)
    )
    state = load_state(state_dir) or default_state(candidate, state_dir)
    mode = detect_mode(candidate)
    if mode == "fresh":
        candidate.mkdir(parents=True, exist_ok=True)
    if args.source_map:
        state["sourceMaps"].update(parse_source_map_args(args.source_map))
    if args.acknowledge_migration:
        state["migrationAcknowledged"] = True
    summary = build_mode_summary(candidate, state, mode)
    summary["migrationAcknowledged"] = state["migrationAcknowledged"]
    state["mode"] = mode
    state["modeSummary"] = summary
    if not state["capabilities"]:
        # Adoption baseline for candidates first seen by the pipeline.
        state["capabilities"] = capability_hashes(candidate)
    save_state(state_dir, state)
    write_json(state_dir / "mode-summary.json", summary)

    print(f"MODE {mode} candidate={candidate}")
    print(f"STATE-DIR {state_dir}")
    if mode == "migrate":
        print(
            f"MIGRATION-SUMMARY legacyFiles={len(summary['legacyFiles'])} "
            f"acknowledged={state['migrationAcknowledged']} "
            f"(details: {state_dir / 'mode-summary.json'})"
        )
        if not state["migrationAcknowledged"]:
            print(
                "NEXT review the migration summary, then re-run "
                "`run_pipeline.py init --acknowledge-migration` before `run`; "
                "no legacy file was modified"
            )
    elif mode == "changed-only":
        capabilities = summary["capabilities"]
        print(
            "CHANGE-SUMMARY "
            f"added={capabilities['added']} "
            f"removed={capabilities['removed']} "
            f"changed={capabilities['changed']} "
            f"unchanged={len(capabilities['unchanged'])}"
        )
        print(f"NOTE {summary['note']}")
    else:
        print("NEXT " + "; ".join(summary["nextSteps"]))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


# ---------------------------------------------------------------------------
# Check execution and persistent evidence
# ---------------------------------------------------------------------------


class StageContext:
    def __init__(
        self,
        candidate: Path,
        state_dir: Path,
        state: dict[str, Any],
        args: argparse.Namespace,
    ) -> None:
        self.candidate = candidate
        self.state_dir = state_dir
        self.state = state
        self.args = args
        self.layout = verification_layout(state_dir)
        self.notes: list[str] = []
        # Live authorizations are per-invocation only; they are never read back
        # from persisted state to justify a later run.
        self.runtime_verify_enabled = bool(getattr(args, "enable_runtime_verify", False))
        self.authorized_writes = set(getattr(args, "authorize_write", None) or [])

    @property
    def source_map_args(self) -> list[str]:
        return [
            f"{source_id}={root}"
            for source_id, root in sorted(self.state.get("sourceMaps", {}).items())
        ]


def check_key(phase: str, scope: str, check_id: str) -> str:
    return f"{phase}--{scope}--{check_id}".replace("/", "_")


def persist_check_record(
    ctx: StageContext,
    *,
    check_id: str,
    name: str,
    phase: str,
    scope_id: str | None,
    scope_key: str,
    command: str,
    resolved_command: str,
    exit_code: int | None,
    status: str,
    started_at: str,
    ended_at: str,
    duration_ms: int,
    log_text: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a check log first, hash it, then store the result record.

    Evidence is written before hashing and never modified afterwards; the log
    header stays deterministic (no timestamps) so repeated runs of
    deterministic checks re-hash equally.
    """
    layout = ctx.layout
    scope = scope_id or "global"
    key = check_key(phase, scope, check_id)
    layout["logs"].mkdir(parents=True, exist_ok=True)
    layout["results"].mkdir(parents=True, exist_ok=True)
    log_relative = f"logs/{key}.log"
    log_path = layout["root"] / log_relative
    log_path.write_text(log_text, encoding="utf-8")
    record = {
        "schemaVersion": CHECKS_SCHEMA,
        "checkId": check_id,
        "name": name,
        "phase": phase,
        "capabilityId": scope_id if scope_key == "capabilityId" else None,
        "workflowId": scope_id if scope_key == "workflowId" else None,
        "command": command,
        "resolvedCommand": resolved_command,
        "exitCode": exit_code,
        "status": status,
        "startedAt": started_at,
        "endedAt": ended_at,
        "durationMs": duration_ms,
        "evidencePath": log_relative,
        "evidenceHash": sha256_file(log_path),
        "hashScope": "persisted-log-file",
    }
    if extra:
        record.update(extra)
    write_json(layout["results"] / f"{key}.json", record)
    return record


def run_subprocess_check(ctx: StageContext, check_id: str, name: str, argv: list[str], portable_command: str) -> dict[str, Any]:
    """Execute one fixed repository-maintained check with an explicit argv."""
    started_at = utc_now()
    monotonic_start = time.monotonic()
    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
    )
    duration_ms = int((time.monotonic() - monotonic_start) * 1000)
    ended_at = utc_now()
    status = "passed" if completed.returncode == 0 else "failed"
    log_lines = [
        f"checkId: {check_id}",
        "phase: global",
        "scope: global",
        f"declared-command: {portable_command}",
        f"resolved-command: {' '.join(shlex.quote(part) for part in argv)}",
        f"exit-code: {completed.returncode}",
        "--- stdout ---",
    ]
    log_text = "\n".join(log_lines) + "\n" + completed.stdout
    if completed.stderr:
        log_text += "\n--- stderr ---\n" + completed.stderr
    return persist_check_record(
        ctx,
        check_id=check_id,
        name=name,
        phase="global",
        scope_id=None,
        scope_key="global",
        command=portable_command,
        resolved_command=" ".join(shlex.quote(part) for part in argv),
        exit_code=completed.returncode,
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        log_text=log_text,
    )


# ---------------------------------------------------------------------------
# Stage runners. Each returns (ok, error_summary, commands).
# ---------------------------------------------------------------------------


def run_analyze(ctx: StageContext) -> tuple[bool, str | None, list[str]]:
    candidate = ctx.candidate
    errors: list[str] = []
    documents: dict[str, Any] = {}
    for name in AUTHORING_INPUTS:
        path = candidate / name
        if not path.is_file():
            errors.append(f"{name}: required authoring input is missing")
            continue
        try:
            documents[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            errors.append(f"{name}: cannot parse ({error})")
    if errors:
        return False, "; ".join(errors), ["run_pipeline.py diagnose (contract parse)"]
    topology = documents["source-topology.json"]
    contract = documents["canonical-contract.json"]
    try:
        source_ids = validate_source_topology(topology)
        validate_canonical_contract(contract, source_ids)
    except ContractError as error:
        errors.append(f"canonical-contract.json: {error}")
    diagnostics = Diagnostics()
    source_maps = {
        source_id: Path(root) for source_id, root in ctx.state.get("sourceMaps", {}).items()
    }
    _validate_source_topology_and_evidence(
        topology, contract, Path.cwd(), source_maps, diagnostics
    )
    errors.extend(diagnostics.errors)
    if errors:
        return False, "; ".join(errors[:5]), [
            "run_pipeline.py diagnose (contract + evidence resolution)"
        ]
    ctx.state["capabilities"] = capability_hashes(candidate)
    return True, None, ["run_pipeline.py diagnose (contract + evidence resolution)"]


MARKER_PATTERN = re.compile(
    r"<!-- code2skill-capability-contract-sha256:[a-f0-9]{64} -->"
)


def refresh_document_markers(candidate: Path) -> None:
    """Re-bind the machine SHA-256 markers in the docs to the current derived
    capability contract after re-derivation. Authored prose is never touched;
    only the exact marker comment is replaced.
    """
    contract_file = candidate / "references" / "capability-contracts.json"
    if not contract_file.is_file():
        return
    marker = (
        "<!-- code2skill-capability-contract-sha256:"
        f"{sha256_file(contract_file)} -->"
    )
    for relative in ("SKILL.md", "MCP.zh-CN.md", "references/feature-context.md"):
        path = candidate / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if MARKER_PATTERN.search(text):
            path.write_text(MARKER_PATTERN.sub(marker, text), encoding="utf-8")


def run_generate(ctx: StageContext) -> tuple[bool, str | None, list[str]]:
    candidate = ctx.candidate
    commands: list[str] = []
    # Deterministic compilation first: Canonical Contract -> Function core and
    # MCP adapter. Anything the compiler cannot derive honestly stops here
    # with an exact reason instead of a fabricated artifact.
    compile_argv = [sys.executable, str(SCRIPT_DIR / "compile_artifacts.py"), str(candidate)]
    compiled = subprocess.run(compile_argv, capture_output=True, text=True, check=False)
    commands.append(" ".join(shlex.quote(part) for part in compile_argv))
    if compiled.returncode != 0:
        detail = (compiled.stdout or compiled.stderr).strip().splitlines()
        reasons = [line for line in detail if "requires-review" in line][:3]
        return False, "compile_artifacts.py could not derive every capability: " + "; ".join(
            reasons or (detail[-1:] or ["unknown compile failure"])
        ), commands
    deriver = SCRIPT_DIR / "derive_artifacts.py"
    argv = [sys.executable, str(deriver), str(candidate)]
    completed = subprocess.run(argv, capture_output=True, text=True, check=False)
    commands.append(" ".join(shlex.quote(part) for part in argv))
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        return False, "derive_artifacts.py failed: " + (detail[-1] if detail else ""), commands
    refresh_document_markers(candidate)
    missing = [
        name
        for name in HAND_AUTHORED_FILES
        if name != "portable-workflow-guard.mjs" and not (candidate / name).is_file()
    ]
    if missing:
        return False, "hand-authored artifacts are missing: " + ", ".join(missing), commands
    return True, None, commands


def clear_result_records(ctx: StageContext, phases: set[str]) -> None:
    """Drop stale records of the phases a stage is about to re-run."""
    results_dir = ctx.layout["results"]
    if not results_dir.is_dir():
        return
    for path in sorted(results_dir.glob("*.json")):
        if any(path.name.startswith(f"{phase}--") for phase in phases):
            path.unlink()


def run_verify(ctx: StageContext) -> tuple[bool, str | None, list[str]]:
    candidate = ctx.candidate
    commands: list[str] = []
    failures: list[str] = []
    clear_result_records(ctx, {"behavior", "host", "bypass", "global"})
    # Restore the derived pending verification-matrix baseline (deterministic
    # projection) so static validation always sees the pre-finalization state,
    # even when verify re-runs after a finalize.
    derive_argv = [sys.executable, str(SCRIPT_DIR / "derive_artifacts.py"), str(candidate)]
    derived = subprocess.run(derive_argv, capture_output=True, text=True, check=False)
    commands.append(" ".join(shlex.quote(part) for part in derive_argv))
    if derived.returncode != 0:
        detail = (derived.stderr or derived.stdout).strip().splitlines()
        return False, "derive_artifacts.py failed: " + (detail[-1] if detail else ""), commands
    # Fixed step 1: strict static validation (pre-finalization).
    validator_argv = [
        sys.executable,
        str(SCRIPT_DIR / "validate_artifacts.py"),
        str(candidate),
        "--pre-finalize",
    ]
    for mapping in ctx.source_map_args:
        validator_argv.extend(["--source-map", mapping])
    static_record = run_subprocess_check(
        ctx,
        STANDARD_CHECK_STATIC,
        "strict artifact validation (pre-finalize)",
        validator_argv,
        "python3 $CODE2SKILL_SCRIPTS/validate_artifacts.py $CANDIDATE --pre-finalize [--source-map ...]",
    )
    commands.append(static_record["resolvedCommand"])
    if static_record["status"] != "passed":
        failures.append(
            f"{STANDARD_CHECK_STATIC} failed; see {static_record['evidencePath']}"
        )
    # Fixed step 2: detached MCP protocol probe in offline mode (a protocol
    # test only: initialize/tools-list/protocol errors/dry-run; it is not a
    # network-isolation proof). Dry-run cases for write Tools are derived from
    # the Canonical input schemas by the pipeline itself.
    node_missing = shutil.which("node") is None
    if node_missing:
        failures.append(f"{STANDARD_CHECK_PROBE} failed: node is not available on PATH")
        failures.append(f"{STANDARD_CHECK_VECTORS} failed: node is not available on PATH")
    else:
        dry_cases_dir = ctx.layout["dry_run_cases"]
        dry_cases_dir.mkdir(parents=True, exist_ok=True)
        for stale in dry_cases_dir.glob("*.json"):
            stale.unlink()
        contract = load_json(
            candidate / "canonical-contract.json", "canonical-contract.json"
        )
        probe_argv = [
            sys.executable,
            str(SCRIPT_DIR / "probe_mcp.py"),
            str(candidate),
            "--offline",
        ]
        for item in contract.get("capabilities", []):
            if not isinstance(item, dict) or item.get("sideEffect", "read") == "read":
                continue
            case_path = dry_cases_dir / f"{item['toolName']}.json"
            write_json(
                case_path,
                {
                    "name": item["toolName"],
                    "arguments": run_vectors.sample_arguments(item),
                },
            )
            probe_argv.extend(["--dry-run-call", str(case_path)])
        probe_record = run_subprocess_check(
            ctx,
            STANDARD_CHECK_PROBE,
            "detached MCP protocol probe (offline)",
            probe_argv,
            "python3 $CODE2SKILL_SCRIPTS/probe_mcp.py $CANDIDATE --offline [--dry-run-call ...]",
        )
        commands.append(probe_record["resolvedCommand"])
        if probe_record["status"] != "passed":
            failures.append(
                f"{STANDARD_CHECK_PROBE} failed; see {probe_record['evidencePath']}"
            )
        # Fixed step 3: deterministic offline behavior vectors derived from the
        # Canonical Contract (Function/Goal/mock-dispatcher vectors).
        vectors_record = run_subprocess_check(
            ctx,
            STANDARD_CHECK_VECTORS,
            "deterministic offline behavior vectors",
            [
                sys.executable,
                str(SCRIPT_DIR / "run_vectors.py"),
                str(candidate),
                "--out",
                str(ctx.layout["vectors"]),
            ],
            "python3 $CODE2SKILL_SCRIPTS/run_vectors.py $CANDIDATE --out $VERIFICATION/vectors",
        )
        commands.append(vectors_record["resolvedCommand"])
        vector_ok, vector_failures = register_vector_results(ctx, vectors_record)
        if not vector_ok:
            failures.extend(vector_failures)
    if failures:
        return False, "; ".join(failures[:5]), commands
    return True, None, commands


def register_vector_results(
    ctx: StageContext, vectors_record: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Register per-check records from the fixed vector run into evidence."""
    if vectors_record["status"] != "passed":
        return False, [
            f"{STANDARD_CHECK_VECTORS} failed; see {vectors_record['evidencePath']}"
        ]
    summary_path = ctx.layout["vectors"] / "vector-summary.json"
    if not summary_path.is_file():
        return False, [f"{STANDARD_CHECK_VECTORS} produced no summary"]
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return False, [f"{STANDARD_CHECK_VECTORS} summary is invalid: {error}"]
    failures: list[str] = []
    verification_root = ctx.layout["root"].resolve()
    for check in summary.get("checks", []):
        check_id = check.get("checkId")
        scope = check.get("capabilityId") or "global"
        evidence_relative = check.get("evidence")
        if not isinstance(evidence_relative, str):
            failures.append(f"{check_id}: vector evidence path missing")
            continue
        evidence_path = (ctx.layout["vectors"] / evidence_relative).resolve()
        if not evidence_path.is_relative_to(verification_root) or not evidence_path.is_file():
            failures.append(f"{check_id}: vector evidence escapes or is missing")
            continue
        persisted = ctx.layout["vectors"] / evidence_relative
        record_path = ctx.layout["results"] / f"{check_key('behavior', scope, check_id)}.json"
        write_json(
            record_path,
            {
                "schemaVersion": CHECKS_SCHEMA,
                "checkId": check_id,
                "name": f"offline vector {check_id}",
                "phase": "behavior",
                "capabilityId": check.get("capabilityId"),
                "workflowId": None,
                "command": "python3 $CODE2SKILL_SCRIPTS/run_vectors.py $CANDIDATE --out $VERIFICATION/vectors",
                "resolvedCommand": vectors_record["resolvedCommand"],
                "exitCode": 0 if check.get("status") == "passed" else 1,
                "status": "passed" if check.get("status") == "passed" else "failed",
                "startedAt": vectors_record["startedAt"],
                "endedAt": vectors_record["endedAt"],
                "durationMs": vectors_record["durationMs"],
                "evidencePath": f"vectors/vector-evidence/{evidence_path.name}",
                "evidenceHash": sha256_file(persisted),
                "hashScope": "persisted-vector-evidence",
            },
        )
        if check.get("status") != "passed":
            failures.append(
                f"{check_id} ({scope}) failed; see vectors/vector-evidence/{evidence_path.name}"
            )
    for uncovered in summary.get("uncovered", []):
        ctx.notes.append(
            f"uncovered: {uncovered.get('checkId')} ({uncovered.get('capabilityId')}): "
            f"{uncovered.get('reason')}"
        )
    return (not failures, failures)


def clear_live_evidence(ctx: StageContext) -> None:
    live_dir = ctx.layout["live"]
    if not live_dir.is_dir():
        return
    for path in sorted(live_dir.glob("*.json")):
        if not path.name.startswith("no-runtime-verification."):
            path.unlink()


def live_case_for(
    ctx: StageContext, capability: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve the explicit live case for one capability.

    The fixed caller never fabricates business input: cases come from
    ``verification/cases/live/<capabilityId>.json`` (caller-sanitized), and
    only capabilities with no required inputs get a mechanical empty case.
    """
    capability_id = capability["capabilityId"]
    tool_name = capability["toolName"]
    case_path = ctx.layout["cases"] / "live" / f"{capability_id}.json"
    if case_path.is_file():
        try:
            case = json.loads(case_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            return None, f"live case {case_path.name} is not valid JSON: {error}"
        if (
            not isinstance(case, dict)
            or case.get("name") != tool_name
            or not isinstance(case.get("arguments"), dict)
        ):
            return None, f"live case must name Tool {tool_name} with object arguments"
        schema_projection = derive_schema_contract(
            {"contractId": "live-case-validation", "capabilities": [capability], "workflows": []}
        )
        input_schema = next(
            (
                item.get("inputSchema")
                for item in schema_projection.get("capabilities", [])
                if isinstance(item, dict)
            ),
            None,
        )
        errors = json_schema_errors(case["arguments"], input_schema)
        if errors:
            return None, "live case arguments violate the Canonical inputSchema: " + "; ".join(
                errors[:3]
            )
        return {"name": tool_name, "arguments": case["arguments"]}, None
    required_inputs = [
        item
        for item in capability.get("inputs", [])
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item.get("required") is True
        and not item.get("requiredWhen")
    ]
    if required_inputs:
        return None, "no-live-case"
    return {"name": tool_name, "arguments": {}}, None


def execute_live_call(
    ctx: StageContext, capability: dict[str, Any], call: dict[str, Any]
) -> tuple[dict[str, Any], tuple[str, str] | None]:
    """The repository-fixed live caller: one real stdio tools/call per scope.

    The call comes from an explicit, caller-sanitized case file (or the
    mechanical empty case for zero-input Tools) — never from fabricated
    business arguments. The persisted evidence pair keeps the explicit shape
    the finalizer expects; the pipeline does not generically redact business
    data, so enabling runtime verification is the operator's statement that
    this environment's inputs and results may be persisted.
    """
    from probe_mcp import StdioMcpClient, initialize

    capability_id = capability["capabilityId"]
    tool_name = capability["toolName"]
    arguments = call["arguments"]
    started_at = utc_now()
    monotonic_start = time.monotonic()
    call = {"name": tool_name, "arguments": arguments}
    result: Any = None
    error_note: str | None = None
    process = subprocess.Popen(
        ["node", "mcp-tool/index.mjs"],
        cwd=ctx.candidate,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        client = StdioMcpClient(process, 15.0)
        initialize(client)
        response = client.request("tools/call", call)
        if "error" in response:
            error_note = f"protocol error: {response['error']}"
        else:
            result = response.get("result")
            if not isinstance(result, dict) or result.get("isError") is not False:
                error_note = f"live call returned isError: {str(result)[:200]}"
            else:
                structured = result.get("structuredContent")
                if not isinstance(structured, dict) or not isinstance(
                    structured.get("data"), (dict, list)
                ):
                    error_note = "live result must contain structuredContent.data"
                    result = None
    except Exception as error:  # probe client errors surface as failed records
        error_note = f"{type(error).__name__}: {error}"
    finally:
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
    duration_ms = int((time.monotonic() - monotonic_start) * 1000)
    ended_at = utc_now()
    layout = ctx.layout
    layout["live"].mkdir(parents=True, exist_ok=True)
    status = "passed" if error_note is None else "failed"
    live_input_relative = f"live/{capability_id}.input.json"
    live_result_relative = f"live/{capability_id}.result.json"
    extra: dict[str, Any] = {}
    if status == "passed":
        write_json(
            layout["root"] / live_input_relative,
            {"capabilities": [{"capabilityId": capability_id, "input": call}]},
        )
        write_json(
            layout["root"] / live_result_relative,
            {"capabilities": [{"capabilityId": capability_id, "result": result}]},
        )
        extra = {
            "toolName": tool_name,
            "inputHash": digest_json(call),
            "resultHash": digest_json(result),
            "liveInputPath": live_input_relative,
            "liveResultPath": live_result_relative,
        }
    log_lines = [
        f"checkId: runtime-call-{capability_id}",
        "phase: runtime",
        f"scope: {capability_id}",
        "caller: repository-fixed live caller (node stdio tools/call)",
        f"tool: {tool_name}",
        f"arguments: {json.dumps(arguments, ensure_ascii=False, sort_keys=True)}",
        f"status: {status}",
    ]
    if error_note:
        log_lines.append(f"error: {error_note}")
    record = persist_check_record(
        ctx,
        check_id=f"runtime-call-{capability_id}",
        name=f"live call {tool_name}",
        phase="runtime",
        scope_id=capability_id,
        scope_key="capabilityId",
        command="pipeline fixed live caller: tools/call with schema-derived arguments",
        resolved_command="node mcp-tool/index.mjs (stdio tools/call)",
        exit_code=0 if status == "passed" else 1,
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        log_text="\n".join(log_lines) + "\n",
        extra=extra,
    )
    if status != "passed":
        return record, None
    return record, (live_input_relative, live_result_relative)


def run_runtime_verify(ctx: StageContext) -> tuple[bool, str | None, list[str]]:
    candidate = ctx.candidate
    authorized_writes = set(ctx.authorized_writes)
    runtime = ctx.state.setdefault("runtimeVerify", {})
    runtime["lastRun"] = {
        "enabled": True,
        "authorizedWrites": sorted(authorized_writes),
        "ranAt": utc_now(),
    }
    clear_result_records(ctx, {"runtime"})
    clear_live_evidence(ctx)
    contract = load_json(
        candidate / "canonical-contract.json", "canonical-contract.json"
    )
    capabilities = [
        item
        for item in contract.get("capabilities", [])
        if isinstance(item, dict) and isinstance(item.get("capabilityId"), str)
    ]
    capabilities_by_id = {item["capabilityId"]: item for item in capabilities}
    side_effects = {
        item["capabilityId"]: item.get("sideEffect", "read") for item in capabilities
    }
    commands = ["pipeline fixed live caller (node stdio tools/call)"]
    failures: list[str] = []
    skipped: list[dict[str, str]] = []
    live_pairs: dict[str, tuple[str, str]] = {}
    for capability in capabilities:
        capability_id = capability["capabilityId"]
        if (
            side_effects.get(capability_id, "read") != "read"
            and capability_id not in authorized_writes
        ):
            skipped.append(
                {
                    "checkId": f"runtime-call-{capability_id}",
                    "capabilityId": capability_id,
                    "reason": "write-authorization-required",
                }
            )
            ctx.notes.append(
                f"skipped runtime-call-{capability_id}: write capability "
                "requires --authorize-write on the same run"
            )
            continue
        case, problem = live_case_for(ctx, capability)
        if case is None:
            if problem == "no-live-case":
                skipped.append(
                    {
                        "checkId": f"runtime-call-{capability_id}",
                        "capabilityId": capability_id,
                        "reason": "no-live-case",
                    }
                )
                ctx.notes.append(
                    f"skipped runtime-call-{capability_id}: provide a sanitized "
                    f"case at verification/cases/live/{capability_id}.json"
                )
            else:
                failures.append(f"runtime-call-{capability_id}: {problem}")
            continue
        record, pair = execute_live_call(ctx, capability, case)
        if pair is not None:
            live_pairs[capability_id] = pair
        else:
            failures.append(
                f"runtime-call-{capability_id} failed; see {record['evidencePath']}"
            )
    # Workflow runtime phases bind the entry capability's live call; every
    # write member of the workflow must be explicitly authorized first.
    for workflow in contract.get("workflows", []):
        if not isinstance(workflow, dict) or not isinstance(workflow.get("workflowId"), str):
            continue
        workflow_id = workflow["workflowId"]
        entry_id = workflow.get("entryCapabilityId")
        entry_capability = capabilities_by_id.get(entry_id)
        if entry_capability is None:
            failures.append(f"workflow {workflow_id}: unknown entry capability {entry_id}")
            continue
        member_writes = sorted(
            capability_id
            for capability_id in set(workflow.get("capabilityIds", [])) | {entry_id}
            if side_effects.get(capability_id, "read") != "read"
        )
        unauthorized = [
            capability_id
            for capability_id in member_writes
            if capability_id not in authorized_writes
        ]
        if unauthorized:
            skipped.append(
                {
                    "checkId": f"runtime-workflow-{workflow_id}",
                    "capabilityId": entry_id,
                    "reason": "write-authorization-required",
                }
            )
            ctx.notes.append(
                f"skipped runtime-workflow-{workflow_id}: authorize write "
                f"capabilities first: {', '.join(unauthorized)}"
            )
            continue
        pair = live_pairs.get(entry_id)
        if pair is None:
            case, problem = live_case_for(ctx, entry_capability)
            if case is None:
                if problem == "no-live-case":
                    skipped.append(
                        {
                            "checkId": f"runtime-workflow-{workflow_id}",
                            "capabilityId": entry_id,
                            "reason": "no-live-case",
                        }
                    )
                    continue
                failures.append(f"runtime-workflow-{workflow_id}: {problem}")
                continue
            record, pair = execute_live_call(ctx, entry_capability, case)
            if pair is not None:
                live_pairs[entry_id] = pair
            else:
                failures.append(
                    f"runtime-workflow-{workflow_id} entry call failed; "
                    f"see {record['evidencePath']}"
                )
                continue
        entry_record_path = ctx.layout["results"] / (
            f"{check_key('runtime', entry_id, f'runtime-call-{entry_id}')}.json"
        )
        entry_record = json.loads(entry_record_path.read_text(encoding="utf-8"))
        workflow_record = dict(entry_record)
        workflow_record.update(
            {
                "checkId": f"runtime-workflow-{workflow_id}",
                "name": f"live workflow entry call {entry_id}",
                "capabilityId": None,
                "workflowId": workflow_id,
            }
        )
        write_json(
            ctx.layout["results"]
            / f"{check_key('runtime', workflow_id, f'runtime-workflow-{workflow_id}')}.json",
            workflow_record,
        )
    runtime["lastSkipped"] = skipped
    if failures:
        return False, "; ".join(failures[:5]), commands
    return True, None, commands


# ---------------------------------------------------------------------------
# Verification report assembly, evidence guard, finalize stage
# ---------------------------------------------------------------------------


def load_result_records(ctx: StageContext) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    results_dir = ctx.layout["results"]
    if not results_dir.is_dir():
        return records
    for path in sorted(results_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("checkId"):
            records.append(record)
    return records


def report_check_dict(record: dict[str, Any]) -> dict[str, Any]:
    check: dict[str, Any] = {
        "checkId": record["checkId"],
        "name": record.get("name", record["checkId"]),
        "command": record["command"],
        "exitCode": record["exitCode"],
        "status": "passed",
        "evidenceHash": record["evidenceHash"],
    }
    if record.get("phase") in {"behavior", "runtime", "host", "bypass"}:
        check["phase"] = record["phase"]
    for key in ("toolName", "inputHash", "resultHash"):
        if record.get(key):
            check[key] = record[key]
    if record.get("zeroExternalWrites") is not None:
        check["zeroExternalWrites"] = record["zeroExternalWrites"]
    return check


def phase_outcome(
    records: list[dict[str, Any]],
    *,
    phase: str,
    scope_id: str,
    scope_key: str,
    expected_ids: set[str],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Decide one phase status honestly from persisted check records."""
    scoped = [
        record
        for record in records
        if record.get("phase") == phase and record.get(scope_key) == scope_id
    ]
    if any(record.get("status") == "failed" for record in scoped):
        return "failed", [], []
    passed = [record for record in scoped if record.get("status") == "passed"]
    passed_ids = {record["checkId"] for record in passed}
    missing = expected_ids - passed_ids
    if not missing and passed:
        return "passed", [report_check_dict(record) for record in passed], passed
    if passed:
        return "requires-review", [], passed
    return "not-run", [], passed


def build_verification_report(
    ctx: StageContext,
) -> tuple[dict[str, Any] | None, list[tuple[str, str]], list[dict[str, Any]], list[str]]:
    """Assemble the vNext verification report from persisted check records.

    Returns (report, live_pairs, used_records, problems). Runtime and Host
    phases are driven purely by persisted records: a phase can be marked
    passed only when this run's evidence exists, is live/receipt bound, and
    covers the canonical minimum checks.
    """
    candidate = ctx.candidate
    problems: list[str] = []
    try:
        contract = load_json(
            candidate / "canonical-contract.json", "canonical-contract.json"
        )
    except PipelineError as error:
        return None, [], [], [str(error)]
    records = load_result_records(ctx)
    used_records: list[dict[str, Any]] = []

    global_records = [
        record
        for record in records
        if record.get("phase") == "global" and record.get("status") == "passed"
    ]
    global_checks = [report_check_dict(record) for record in global_records]
    global_ids = {check["checkId"] for check in global_checks}
    for standard in sorted(STANDARD_CHECK_IDS):
        if standard not in global_ids:
            problems.append(f"standard offline check {standard} has no passed evidence")
    used_records.extend(global_records)

    capabilities_report: list[dict[str, Any]] = []
    live_pairs: list[tuple[str, str]] = []
    live_capability_ids: set[str] = set()
    for capability in contract.get("capabilities", []):
        if not isinstance(capability, dict) or not isinstance(
            capability.get("capabilityId"), str
        ):
            continue
        capability_id = capability["capabilityId"]
        expected = capability_verification_checks(capability, contract)
        expected_by_phase: dict[str, set[str]] = {
            "behavior": set(),
            "runtime": set(),
            "host": set(),
        }
        for item in expected:
            item_phase = item.get("phase", "behavior") if isinstance(item, dict) else "behavior"
            item_id = item.get("checkId") if isinstance(item, dict) else item
            if item_phase in expected_by_phase and isinstance(item_id, str):
                expected_by_phase[item_phase].add(item_id)

        behavior_status, behavior_checks, behavior_records = phase_outcome(
            records,
            phase="behavior",
            scope_id=capability_id,
            scope_key="capabilityId",
            expected_ids=expected_by_phase["behavior"],
        )
        if behavior_status == "passed":
            used_records.extend(behavior_records)
        runtime_records = [
            record
            for record in records
            if record.get("phase") == "runtime"
            and record.get("capabilityId") == capability_id
        ]
        runtime_status, runtime_checks, runtime_passed = phase_outcome(
            records,
            phase="runtime",
            scope_id=capability_id,
            scope_key="capabilityId",
            expected_ids=expected_by_phase["runtime"],
        )
        if runtime_status == "passed":
            bound = [
                record
                for record in runtime_passed
                if record.get("inputHash") and record.get("resultHash")
            ]
            if not bound:
                runtime_status = "requires-review"
                runtime_checks = []
                problems.append(
                    f"capability {capability_id}: passed runtime checks lack live "
                    "input/result binding; runtime stays unverified"
                )
        host_status, host_checks, host_records = phase_outcome(
            records,
            phase="host",
            scope_id=capability_id,
            scope_key="capabilityId",
            expected_ids=expected_by_phase["host"],
        )
        if host_status == "passed":
            used_records.extend(host_records)
        if runtime_status == "passed":
            used_records.extend(runtime_passed)
        capabilities_report.append(
            {
                "capabilityId": capability_id,
                "behavior": {"status": behavior_status, "checks": behavior_checks},
                "runtime": {"status": runtime_status, "checks": runtime_checks},
                "host": {"status": host_status, "checks": host_checks},
            }
        )
        if runtime_status == "passed" and capability_id not in live_capability_ids:
            bound_record = next(
                record
                for record in runtime_passed
                if record.get("liveInputPath")
            )
            live_pairs.append(
                (bound_record["liveInputPath"], bound_record["liveResultPath"])
            )
            live_capability_ids.add(capability_id)

    workflows_report: list[dict[str, Any]] = []
    for workflow in contract.get("workflows", []):
        if not isinstance(workflow, dict) or not isinstance(
            workflow.get("workflowId"), str
        ):
            continue
        workflow_id = workflow["workflowId"]
        declared_checks = workflow.get("verificationChecks", [])
        expected_workflow: dict[str, set[str]] = {
            "bypass": set(),
            "runtime": set(),
            "host": set(),
        }
        for item in declared_checks if isinstance(declared_checks, list) else []:
            item_phase = item.get("phase") if isinstance(item, dict) else "bypass"
            item_id = item.get("checkId") if isinstance(item, dict) else item
            if item_phase in expected_workflow and isinstance(item_id, str):
                expected_workflow[item_phase].add(item_id)
        bypass_status, bypass_checks, bypass_records = phase_outcome(
            records,
            phase="bypass",
            scope_id=workflow_id,
            scope_key="workflowId",
            expected_ids=expected_workflow["bypass"],
        )
        if bypass_status == "passed":
            if not all(
                check.get("zeroExternalWrites") is True for check in bypass_checks
            ):
                bypass_status = "requires-review"
                bypass_checks = []
                problems.append(
                    f"workflow {workflow_id}: bypass checks must all declare "
                    "zeroExternalWrites: true"
                )
            else:
                used_records.extend(bypass_records)
        workflow_runtime_status, workflow_runtime_checks, workflow_runtime_records = phase_outcome(
            records,
            phase="runtime",
            scope_id=workflow_id,
            scope_key="workflowId",
            expected_ids=expected_workflow["runtime"],
        )
        if workflow_runtime_status == "passed":
            used_records.extend(workflow_runtime_records)
        workflow_host_status, workflow_host_checks, workflow_host_records = phase_outcome(
            records,
            phase="host",
            scope_id=workflow_id,
            scope_key="workflowId",
            expected_ids=expected_workflow["host"],
        )
        if workflow_host_status == "passed":
            used_records.extend(workflow_host_records)
        workflows_report.append(
            {
                "workflowId": workflow_id,
                "bypass": {"status": bypass_status, "checks": bypass_checks},
                "runtime": {
                    "status": workflow_runtime_status,
                    "checks": workflow_runtime_checks,
                },
                "host": {"status": workflow_host_status, "checks": workflow_host_checks},
            }
        )

    if not global_checks:
        problems.append("no passed global checks; run the verify stage first")
    if problems:
        return None, [], [], problems
    all_phases = [
        phase["status"]
        for record in capabilities_report
        for phase in (record["behavior"], record["runtime"], record["host"])
    ] + [
        phase["status"]
        for record in workflows_report
        for phase in (record["bypass"], record["runtime"], record["host"])
    ]
    report = {
        "schemaVersion": "vNext",
        "contractId": contract["contractId"],
        "status": "passed" if all(status == "passed" for status in all_phases) else "partial",
        "checks": global_checks,
        "capabilities": capabilities_report,
        "workflows": workflows_report,
    }
    return report, live_pairs, used_records, []


def guard_evidence(
    ctx: StageContext, used_records: list[dict[str, Any]]
) -> list[str]:
    """Refuse missing, escaped, or tampered evidence before finalization.

    Every record the assembled report relies on is re-checked directly (no
    checkId re-lookup, so one capability's evidence can never be mistaken for
    another's): the persisted log must exist inside the verification directory
    (symlinks resolving outside count as escapes) and match its recorded hash,
    and live pairs must still replay to the recorded input/result hashes.
    """
    problems: list[str] = []
    verification_root = ctx.layout["root"].resolve()
    seen: set[int] = set()
    for record in used_records:
        if id(record) in seen:
            continue
        seen.add(id(record))
        check_id = record.get("checkId", "unknown")
        scope = record.get("capabilityId") or record.get("workflowId") or "global"
        label = f"check {check_id} ({scope})"
        evidence_relative = record.get("evidencePath")
        if not isinstance(evidence_relative, str) or not evidence_relative:
            problems.append(f"{label} has no persisted evidence path")
            continue
        evidence_path = (ctx.layout["root"] / evidence_relative).resolve()
        if not evidence_path.is_relative_to(verification_root):
            problems.append(
                f"{label} evidence escapes the persistent verification "
                f"directory: {evidence_relative}"
            )
            continue
        if not evidence_path.is_file():
            problems.append(
                f"{label} evidence is missing: {evidence_relative}; "
                "re-run the producing stage instead of referencing temporary files"
            )
            continue
        actual = sha256_file(evidence_path)
        if actual != record.get("evidenceHash"):
            problems.append(
                f"{label} evidence was modified after hashing: "
                f"{evidence_relative}"
            )
        if record.get("liveInputPath"):
            problem = guard_live_replay(ctx, record)
            if problem:
                problems.append(f"{label}: {problem}")
    return problems


def guard_live_replay(ctx: StageContext, record: dict[str, Any]) -> str | None:
    """Recompute live input/result hashes so receipts must stay replayable."""
    input_path = ctx.layout["root"] / record["liveInputPath"]
    result_path = ctx.layout["root"] / record["liveResultPath"]
    for label, path in (("liveInput", input_path), ("liveResult", result_path)):
        if not path.is_file():
            return f"{label} evidence is missing: {record[f'{label}Path']}"
    try:
        input_document = json.loads(input_path.read_text(encoding="utf-8"))
        result_document = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return f"live evidence is not valid JSON: {error}"

    def entries(document: Any) -> list[dict[str, Any]]:
        if isinstance(document, dict) and isinstance(document.get("capabilities"), list):
            return document["capabilities"]
        if isinstance(document, list):
            return document
        return [document]

    def payload(item: dict[str, Any], kind: str) -> Any:
        preferred = "input" if kind == "input" else "result"
        if preferred in item:
            return item[preferred]
        return {key: value for key, value in item.items() if key != "capabilityId"}

    capability_id = record.get("capabilityId")
    input_entry = next(
        (item for item in entries(input_document) if item.get("capabilityId") == capability_id),
        None,
    )
    result_entry = next(
        (item for item in entries(result_document) if item.get("capabilityId") == capability_id),
        None,
    )
    if input_entry is None or result_entry is None:
        return f"live evidence no longer contains capabilityId {capability_id}"
    if digest_json(payload(input_entry, "input")) != record.get("inputHash"):
        return "live input evidence was modified after hashing"
    if digest_json(payload(result_entry, "result")) != record.get("resultHash"):
        return "live result evidence was modified after hashing"
    return None


def run_finalize(ctx: StageContext) -> tuple[bool, str | None, list[str]]:
    candidate = ctx.candidate
    commands: list[str] = []
    # Restore the derived pending verification-matrix baseline first: the
    # finalizer's pre-check requires it, and re-deriving an unchanged contract
    # is deterministic. This also makes repeated finalize runs safe.
    derive_argv = [sys.executable, str(SCRIPT_DIR / "derive_artifacts.py"), str(candidate)]
    derived = subprocess.run(derive_argv, capture_output=True, text=True, check=False)
    commands.append(" ".join(shlex.quote(part) for part in derive_argv))
    if derived.returncode != 0:
        detail = (derived.stderr or derived.stdout).strip().splitlines()
        return False, "derive_artifacts.py failed: " + (detail[-1] if detail else ""), commands
    report, live_pairs, used_records, problems = build_verification_report(ctx)
    if report is None:
        return False, "; ".join(problems[:5]), commands
    evidence_problems = guard_evidence(ctx, used_records)
    if evidence_problems:
        return False, "; ".join(evidence_problems[:5]), commands
    reports_dir = ctx.layout["reports"]
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "verification-report.json"
    write_json(report_path, report)
    live_dir = ctx.layout["live"]
    live_dir.mkdir(parents=True, exist_ok=True)
    finalizer_argv = [
        sys.executable,
        str(SCRIPT_DIR / "finalize_export.py"),
        str(candidate),
        "--verification-report",
        str(report_path),
    ]
    for mapping in ctx.source_map_args:
        finalizer_argv.extend(["--source-map", mapping])
    if live_pairs:
        for live_input, live_result in live_pairs:
            finalizer_argv.extend(
                [
                    "--live-input",
                    str(ctx.layout["root"] / live_input),
                    "--live-result",
                    str(ctx.layout["root"] / live_result),
                ]
            )
    else:
        empty_input = live_dir / "no-runtime-verification.input.json"
        empty_result = live_dir / "no-runtime-verification.result.json"
        write_json(empty_input, {"capabilities": []})
        write_json(empty_result, {"capabilities": []})
        finalizer_argv.extend(
            ["--live-input", str(empty_input), "--live-result", str(empty_result)]
        )
    completed = subprocess.run(
        finalizer_argv, capture_output=True, text=True, check=False
    )
    commands.append(" ".join(shlex.quote(part) for part in finalizer_argv))
    log_path = reports_dir / "finalizer-output.log"
    log_path.write_text(
        (completed.stdout or "") + "\n--- stderr ---\n" + (completed.stderr or ""),
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        return False, "finalize_export.py failed: " + (detail[-1] if detail else ""), commands
    approval = load_json(candidate / "approval-audit.json", "approval-audit.json")
    matrix = load_json(
        candidate / "verification-matrix.json", "verification-matrix.json"
    )
    ctx.state["lastFinalization"] = {
        "decision": approval.get("decision"),
        "completedAt": utc_now(),
        "delivery": matrix.get("delivery"),
        "capabilities": {
            item.get("capabilityId"): item.get("status")
            for item in matrix.get("capabilities", [])
            if isinstance(item, dict)
        },
    }
    return True, None, commands


# ---------------------------------------------------------------------------
# Run orchestration and reporting
# ---------------------------------------------------------------------------

STAGE_RUNNERS = {
    "analyze": run_analyze,
    "generate": run_generate,
    "verify": run_verify,
    "runtime-verify": run_runtime_verify,
    "finalize": run_finalize,
}


def execute_run(args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    candidate = args.candidate.resolve()
    state_dir = (
        args.state_dir.resolve() if args.state_dir else default_state_dir(candidate)
    )
    state = load_state(state_dir)
    if state is None:
        raise PipelineError(
            f"no producer state found at {state_dir}; run `run_pipeline.py init` first"
        )
    if state.get("mode") == "migrate" and not state.get("migrationAcknowledged"):
        raise PipelineError(
            "migrate mode requires reviewing the migration summary first: "
            "re-run `run_pipeline.py init --acknowledge-migration`"
        )
    ctx = StageContext(candidate, state_dir, state, args)
    runtime_enabled = ctx.runtime_verify_enabled
    authorized_writes = ctx.authorized_writes

    requested: list[str] | None = None
    if args.only:
        requested = [name.strip() for name in args.only.split(",") if name.strip()]
        unknown = sorted(set(requested) - set(STAGES))
        if unknown:
            raise PipelineError(f"unknown stage(s) in --only: {', '.join(unknown)}")
    if not runtime_enabled and requested and "runtime-verify" in requested:
        raise PipelineError(
            "runtime-verify requires --enable-runtime-verify on the same run; "
            "authorization is per-invocation and is never read from state"
        )
    if runtime_enabled and requested and "runtime-verify" not in requested:
        raise PipelineError(
            "--enable-runtime-verify requires the runtime-verify stage to be "
            "selected; remove --only or include runtime-verify"
        )
    selected = list(STAGES) if requested is None else [
        name for name in STAGES if name in requested
    ]
    if not runtime_enabled:
        selected = [name for name in selected if name != "runtime-verify"]

    # Create the persistent verification layout up front so directory creation
    # itself never counts as an input change between runs.
    for path in ctx.layout.values():
        if path.suffix != ".json":
            path.mkdir(parents=True, exist_ok=True)

    def outputs_intact(entry: dict[str, Any]) -> bool:
        hashes = entry.get("outputHashes") or {}
        if not hashes:
            return False
        for relative, digest in hashes.items():
            path = candidate / relative
            if not path.is_file() or sha256_file(path) != digest:
                return False
        return True

    # An --only run may skip earlier stages, but every skipped stage upstream
    # of the first selected stage must be completed and provably current;
    # otherwise the run would silently chain stale upstream proof into the
    # selected stage. Downstream stages are irrelevant to the selection, and
    # runtime-verify is exempt: it is an optional stage whose persisted
    # evidence finalize consumes as-is.
    if requested is not None:
        first_selected = min(STAGES.index(stage) for stage in selected)
        stale = []
        for stage in STAGES[:first_selected]:
            if stage == "runtime-verify":
                continue
            entry = state["stages"][stage]
            fingerprint_inputs = stage_fingerprint_inputs(
                stage, candidate, state_dir, state
            )
            current = fingerprint_of(fingerprint_inputs)
            intact = stage != "finalize" or outputs_intact(entry)
            if (
                entry["status"] != "completed"
                or entry["inputFingerprint"] != current
                or not intact
            ):
                stale.append(stage)
        if stale:
            raise PipelineError(
                "--only may skip only completed, up-to-date stages; stale or "
                f"incomplete upstream stage(s): {', '.join(stale)}. "
                "Run without --only or include them."
            )

    # A previously authorized runtime-verify stays valid only while its inputs
    # hold. Re-check them BEFORE any stage (especially finalize) may reuse its
    # evidence: stale live proof and every conclusion built on it are voided
    # up front, never after the fact.
    runtime_entry = state["stages"]["runtime-verify"]
    if not runtime_enabled and runtime_entry["status"] == "completed":
        stale_inputs = stage_fingerprint_inputs(
            "runtime-verify",
            candidate,
            state_dir,
            state,
            runtime_auth=set(runtime_entry.get("runtimeAuth", [])),
        )
        if runtime_entry["inputFingerprint"] != fingerprint_of(stale_inputs):
            runtime_entry["status"] = "invalidated"
            runtime_entry["invalidatedReason"] = (
                "inputs changed since the authorized live run; live evidence "
                "and its conclusions were voided"
            )
            clear_result_records(ctx, {"runtime"})
            clear_live_evidence(ctx)
            state["lastFinalization"] = None
            save_state(state_dir, state)

    ok = True
    for stage in selected:
        entry = state["stages"][stage]
        fingerprint_inputs = stage_fingerprint_inputs(
            stage,
            candidate,
            state_dir,
            state,
            runtime_auth=authorized_writes,
        )
        fingerprint = fingerprint_of(fingerprint_inputs)
        intact = stage != "finalize" or outputs_intact(entry)
        if (
            entry["status"] == "completed"
            and entry["inputFingerprint"] == fingerprint
            and intact
            and not args.force
        ):
            entry["lastAction"] = "skipped-unchanged"
            entry["skipReason"] = "inputs unchanged since the completed run"
            continue
        if entry["status"] == "completed":
            entry["status"] = "invalidated"
            entry["skipReason"] = None
            if not intact:
                entry["invalidatedReason"] = (
                    "finalization outputs are missing or were modified; "
                    "re-running to restore them"
                )
            save_state(state_dir, state)
        entry["status"] = "running"
        entry["startedAt"] = utc_now()
        entry["endedAt"] = None
        entry["durationMs"] = None
        entry["errorSummary"] = None
        save_state(state_dir, state)
        monotonic_start = time.monotonic()
        stage_ok, error_summary, commands = STAGE_RUNNERS[stage](ctx)
        entry["durationMs"] = int((time.monotonic() - monotonic_start) * 1000)
        entry["endedAt"] = utc_now()
        entry["lastAction"] = "executed"
        entry["command"] = " ; ".join(commands) if commands else None
        entry["runs"] = int(entry.get("runs") or 0) + 1
        if stage_ok:
            entry["status"] = "completed"
            entry["inputFingerprint"] = fingerprint
            entry["fingerprintInputs"] = fingerprint_inputs
            entry["skipReason"] = None
            entry["invalidatedReason"] = None
            if stage == "runtime-verify":
                entry["runtimeAuth"] = sorted(authorized_writes)
            if stage == "finalize":
                entry["outputHashes"] = {
                    relative: sha256_file(candidate / relative)
                    for relative in sorted(FINALIZATION_REL_PATHS)
                    if (candidate / relative).is_file()
                }
        else:
            entry["status"] = "failed"
            entry["errorSummary"] = error_summary
            ok = False
        save_state(state_dir, state)
        if not ok:
            break

    if not runtime_enabled and "runtime-verify" not in selected:
        runtime_entry["lastAction"] = "skipped-disabled"
        runtime_entry["skipReason"] = (
            "runtime verification not enabled for this run; pass "
            "--enable-runtime-verify inside an authorized environment"
        )

    # Dependency DAG: once any stage has failed, every downstream completed
    # stage is stale proof and must be reported as invalidated. Pending or
    # never-enabled optional stages carry no proof and do not propagate.
    broken_by: str | None = None
    for stage in STAGES:
        entry = state["stages"][stage]
        if broken_by is not None and entry["status"] == "completed":
            entry["status"] = "invalidated"
            entry["skipReason"] = None
            entry["invalidatedReason"] = (
                f"upstream stage {broken_by} did not complete; "
                "earlier proof is stale"
            )
        if entry["status"] == "failed" and broken_by is None:
            broken_by = stage
    if state["stages"]["finalize"]["status"] != "completed":
        state["lastFinalization"] = None
    save_state(state_dir, state)
    return state, ok


def build_pipeline_report(state: dict[str, Any]) -> dict[str, Any]:
    stages = {}
    for name in STAGES:
        entry = state["stages"][name]
        stages[name] = {
            "status": entry["status"],
            "lastAction": entry["lastAction"],
            "skipReason": entry["skipReason"],
            "invalidatedReason": entry.get("invalidatedReason"),
            "startedAt": entry["startedAt"],
            "endedAt": entry["endedAt"],
            "durationMs": entry["durationMs"],
            "runs": entry["runs"],
            "command": entry["command"],
            "errorSummary": entry["errorSummary"],
        }
    finalization = state.get("lastFinalization") or {}
    finalize_completed = state["stages"]["finalize"]["status"] == "completed"
    capability_statuses = (
        finalization.get("capabilities", {}) if finalize_completed else {}
    )

    def rollup(flag: str) -> str:
        if not capability_statuses:
            return "no"
        values = [
            bool(status.get(flag))
            for status in capability_statuses.values()
            if isinstance(status, dict)
        ]
        if values and all(values):
            return "yes"
        if any(values):
            return "partial"
        return "no"

    if finalize_completed and capability_statuses:
        delivery = {
            "generated": "yes",
            "behaviorVerified": rollup("behaviorVerified"),
            "runtimeVerified": rollup("runtimeVerified"),
            "hostVerified": rollup("hostVerified"),
            "deployed": "no",
            "source": "verification-matrix.json",
        }
    else:
        behavior_verified = "no"
        # Only a completed verify stage may speak for behavior evidence at
        # all; an invalidated or failed one makes every older record stale.
        if state["stages"]["verify"]["status"] == "completed":
            candidate_path = Path(state["candidateDir"])
            contract_path = candidate_path / "canonical-contract.json"
            contract = None
            if contract_path.is_file():
                try:
                    contract = json.loads(contract_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    contract = None
            if isinstance(contract, dict):
                layout = verification_layout(Path(state["stateDir"]))
                records: list[dict[str, Any]] = []
                results_dir = layout["results"]
                if results_dir.is_dir():
                    for record_path in sorted(results_dir.glob("*.json")):
                        try:
                            record = json.loads(record_path.read_text(encoding="utf-8"))
                        except (OSError, UnicodeError, json.JSONDecodeError):
                            continue
                        if isinstance(record, dict) and record.get("checkId"):
                            records.append(record)
                statuses = []
                for capability in contract.get("capabilities", []):
                    if not isinstance(capability, dict) or not isinstance(
                        capability.get("capabilityId"), str
                    ):
                        continue
                    expected = capability_verification_checks(capability, contract)
                    expected_ids = {
                        item.get("checkId") if isinstance(item, dict) else item
                        for item in expected
                        if (item.get("phase", "behavior") if isinstance(item, dict) else "behavior")
                        == "behavior"
                    }
                    status, _checks, _passed = phase_outcome(
                        records,
                        phase="behavior",
                        scope_id=capability["capabilityId"],
                        scope_key="capabilityId",
                        expected_ids={item for item in expected_ids if isinstance(item, str)},
                    )
                    statuses.append(status)
                if statuses and all(status == "passed" for status in statuses):
                    behavior_verified = "yes"
                elif any(status == "passed" for status in statuses):
                    behavior_verified = "partial"
        delivery = {
            "generated": (
                "yes" if state["stages"]["generate"]["status"] == "completed" else "no"
            ),
            "behaviorVerified": behavior_verified,
            "runtimeVerified": (
                "yes"
                if state["stages"]["runtime-verify"]["status"] == "completed"
                else "no"
            ),
            "hostVerified": "no",
            "deployed": "no",
            "source": "stage-status",
        }
    next_steps: list[str] = []
    for name in STAGES:
        entry = state["stages"][name]
        if entry["status"] == "failed":
            next_steps.append(
                f"resolve the {name} failure: {entry['errorSummary'] or 'see stage logs'}"
            )
            break
    else:
        invalidated = [
            name for name in STAGES if state["stages"][name]["status"] == "invalidated"
        ]
        if invalidated:
            next_steps.append(
                "re-run to refresh stale proof for: " + ", ".join(invalidated)
            )
        if state["stages"]["finalize"]["status"] != "completed":
            next_steps.append("run `run_pipeline.py run` to execute pending stages")
        runtime = state.get("runtimeVerify", {})
        last_run = runtime.get("lastRun") if isinstance(runtime, dict) else None
        if not last_run:
            next_steps.append(
                "runtime verification has not run; it runs only when explicitly "
                "enabled for a single invocation with --enable-runtime-verify"
            )
        skipped_writes = runtime.get("lastSkipped") or []
        for item in skipped_writes:
            next_steps.append(
                f"live write verification for {item['capabilityId']} requires "
                f"--authorize-write {item['capabilityId']} on the same run"
            )
        if delivery["behaviorVerified"] not in {"yes", "no"}:
            next_steps.append(
                "complete behavior coverage for the remaining capabilities, then re-run verify"
            )
    return {
        "schemaVersion": PIPELINE_VERSION,
        "featureId": state["featureId"],
        "mode": state.get("mode"),
        "candidateDir": state["candidateDir"],
        "stateDir": state["stateDir"],
        "runtimeVerify": {
            "authorization": "per-invocation; never persisted",
            **(state.get("runtimeVerify") or {}),
        },
        "stages": stages,
        "delivery": delivery,
        "decision": finalization.get("decision") if finalize_completed else None,
        "nextSteps": next_steps,
        "generatedAt": utc_now(),
    }


def print_human_report(report: dict[str, Any]) -> None:
    print(
        f"PIPELINE feature={report['featureId']} mode={report['mode']} "
        f"decision={report['decision'] or 'n/a'}"
    )
    for name in STAGES:
        stage = report["stages"][name]
        duration = stage["durationMs"]
        duration_text = f"{duration / 1000:.3f}s" if duration is not None else "-"
        action = stage["lastAction"] or "-"
        line = (
            f"STAGE {name:<14} status={stage['status']:<10} "
            f"action={action:<18} duration={duration_text}"
        )
        if stage.get("skipReason"):
            line += f" reason={stage['skipReason']}"
        if stage.get("invalidatedReason"):
            line += f" invalidated={stage['invalidatedReason']}"
        if stage.get("errorSummary"):
            line += f" error={stage['errorSummary']}"
        print(line)
    delivery = report["delivery"]
    print(
        "DELIVERY "
        f"generated={delivery['generated']} "
        f"behavior-verified={delivery['behaviorVerified']} "
        f"runtime-verified={delivery['runtimeVerified']} "
        f"host-verified={delivery['hostVerified']} "
        f"deployed={delivery['deployed']} "
        f"(source: {delivery['source']})"
    )
    for step in report["nextSteps"]:
        print(f"NEXT {step}")


def cmd_run(args: argparse.Namespace) -> int:
    state, ok = execute_run(args)
    report = build_pipeline_report(state)
    write_json(
        Path(state["stateDir"]) / "verification" / "reports" / "pipeline-report.json",
        report,
    )
    print_human_report(report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


def cmd_status(args: argparse.Namespace) -> int:
    candidate = args.candidate.resolve()
    state_dir = (
        args.state_dir.resolve() if args.state_dir else default_state_dir(candidate)
    )
    state = load_state(state_dir)
    if state is None:
        raise PipelineError(
            f"no producer state found at {state_dir}; run `run_pipeline.py init` first"
        )
    report = build_pipeline_report(state)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_human_report(report)
    return 0


# ---------------------------------------------------------------------------
# Diagnostics: root-cause-first aggregation
# ---------------------------------------------------------------------------

CATEGORY_ORDER = (
    "source/topology",
    "canonical",
    "capability",
    "function/mcp",
    "documentation",
    "verification",
    "finalization",
    "other",
)
ROOT_CATEGORIES = {"source/topology", "canonical"}

STAGE_CATEGORY_MAP = {
    "analyze": {"source/topology", "canonical"},
    "generate": {"canonical", "capability", "function/mcp", "documentation"},
    "verify": {"verification", "function/mcp", "capability"},
    "runtime-verify": {"verification"},
    "finalize": {"finalization"},
}


def capability_tokens(candidate: Path) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for filename in ("canonical-contract.json", "capability-bundle.json"):
        path = candidate / filename
        if not path.is_file():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        for item in document.get("capabilities", []) if isinstance(document, dict) else []:
            if not isinstance(item, dict):
                continue
            capability_id = item.get("capabilityId")
            tool_name = item.get("toolName")
            if isinstance(capability_id, str):
                tokens[capability_id] = capability_id
                if isinstance(tool_name, str):
                    tokens[tool_name] = capability_id
    return tokens


def categorize_error(error: str, tokens: dict[str, str]) -> tuple[str, str | None]:
    for token, capability_id in sorted(tokens.items(), key=lambda item: -len(item[0])):
        if token and token in error:
            return f"capability:{capability_id}", capability_id
    location, _separator, _message = error.partition(": ")
    lowered = location.lower()
    if (
        location.startswith("source-topology")
        or location.startswith("--source-map")
        or location.startswith("--source-root")
        or "evidencecatalog" in lowered
    ):
        return "source/topology", None
    if location.startswith(
        (
            "canonical-contract",
            "goal-contract",
            "consumer-requirements",
            "host-profile",
            "host-compatibility-report",
            "capability-bundle",
            "capability-draft",
            "export-profile",
        )
    ):
        return "canonical", None
    if location.startswith("function-core/validation-receipt") or location.startswith(
        ("preflight-report", "approval-audit", "live-verification", "export-manifest", "--verification-report", "--live-")
    ):
        return "finalization", None
    if location.startswith(("function-core", "mcp-tool")):
        return "function/mcp", None
    if location.startswith(
        ("SKILL.md", "MCP.zh-CN.md", "MCP-SETUP.md", "references/")
    ):
        return "documentation", None
    if location.startswith("verification-matrix"):
        return "verification", None
    return "other", None


def split_error(error: str) -> tuple[str, str]:
    location, separator, message = error.partition(": ")
    return (location, message) if separator else ("pipeline", error)


def cmd_diagnose(args: argparse.Namespace) -> int:
    candidate = args.candidate.resolve()
    state_dir = (
        args.state_dir.resolve() if args.state_dir else default_state_dir(candidate)
    )
    source_maps: dict[str, Path] = {}
    state = load_state(state_dir)
    if state is not None:
        source_maps = {
            source_id: Path(root)
            for source_id, root in state.get("sourceMaps", {}).items()
        }
    pre_finalize = not (candidate / "export-manifest.json").is_file()
    diagnostics = Diagnostics()
    if not candidate.is_dir():
        diagnostics.error("candidate", f"candidate directory does not exist: {candidate}")
    else:
        validate(candidate, Path.cwd(), pre_finalize, diagnostics, source_maps)
    tokens = capability_tokens(candidate) if candidate.is_dir() else {}
    grouped: dict[str, list[str]] = {}
    for error in diagnostics.errors:
        category, _capability_id = categorize_error(error, tokens)
        if args.capability and category != f"capability:{args.capability}":
            continue
        grouped.setdefault(category, []).append(error)
    if args.stage:
        allowed = STAGE_CATEGORY_MAP.get(args.stage)
        if allowed is None:
            raise PipelineError(
                f"unknown stage {args.stage}; expected one of {sorted(STAGE_CATEGORY_MAP)}"
            )
        grouped = {
            category: errors
            for category, errors in grouped.items()
            if category in allowed or category.startswith("capability:") and "capability" in allowed
        }
    total = sum(len(errors) for errors in grouped.values())
    ordered_categories = sorted(
        grouped,
        key=lambda name: (
            next(
                (index for index, item in enumerate(CATEGORY_ORDER) if name == item or name.startswith(item + ":")),
                len(CATEGORY_ORDER),
            )
        ),
    )
    root_present = any(category in ROOT_CATEGORIES for category in grouped)
    max_errors = None if args.full else max(1, args.max_errors)

    payload: dict[str, Any] = {
        "candidate": str(candidate),
        "preFinalize": pre_finalize,
        "errors": total,
        "categories": [],
        "suppressedDownstream": {},
    }
    lines = [
        f"DIAGNOSIS candidate={candidate} errors={total} "
        f"phase={'pre-finalize' if pre_finalize else 'final'}"
    ]
    shown_root = False
    for category in ordered_categories:
        errors = grouped[category]
        is_root = category in ROOT_CATEGORIES
        if root_present and not is_root and not args.full:
            payload["suppressedDownstream"][category] = len(errors)
            continue
        header = "ROOT-CAUSE" if is_root and root_present else "CATEGORY"
        limit = len(errors) if max_errors is None else min(max_errors, len(errors))
        lines.append(f"{header} {category} ({len(errors)} error(s)):")
        lines.extend(f"  {error}" for error in errors[:limit])
        if len(errors) > limit:
            lines.append(
                f"  ... {len(errors) - limit} more; re-run with --full for the complete list"
            )
        payload["categories"].append(
            {
                "category": category,
                "rootCause": bool(is_root and root_present),
                "count": len(errors),
                "errors": errors if args.full else errors[:limit],
            }
        )
        shown_root = shown_root or is_root
    if payload["suppressedDownstream"]:
        suppressed_total = sum(payload["suppressedDownstream"].values())
        lines.append(
            f"DOWNSTREAM-SUPPRESSED {suppressed_total} error(s): "
            + ", ".join(
                f"{name}={count}"
                for name, count in sorted(payload["suppressedDownstream"].items())
            )
            + " (fix the root causes above, then re-run diagnose; --full shows everything)"
        )
    if total == 0:
        lines.append("OK no validation errors")
    output = "\n".join(lines)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(output)
    return 0 if total == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("candidate", type=Path, help="candidate export directory")
        sub.add_argument(
            "--state-dir",
            type=Path,
            default=None,
            help="Producer sidecar directory (default: <candidate>.producer-state)",
        )
        sub.add_argument("--json", action="store_true", help="also print machine-readable JSON")

    init_parser = subparsers.add_parser(
        "init", help="detect the processing mode and create producer state"
    )
    add_common(init_parser)
    init_parser.add_argument(
        "--source-map",
        action="append",
        default=[],
        metavar="SOURCE_ID=PATH",
        help="authorized source root; repeat for every declared source",
    )
    init_parser.add_argument(
        "--acknowledge-migration",
        action="store_true",
        help="confirm the migrate-mode summary was reviewed before any modification",
    )
    init_parser.set_defaults(handler=cmd_init)

    run_parser = subparsers.add_parser(
        "run", help="execute pending pipeline stages with resume support"
    )
    add_common(run_parser)
    run_parser.add_argument(
        "--only",
        default=None,
        help="comma-separated subset of analyze,generate,verify,runtime-verify,finalize",
    )
    run_parser.add_argument(
        "--force",
        action="store_true",
        help="re-execute selected stages even when inputs are unchanged",
    )
    run_parser.add_argument(
        "--enable-runtime-verify",
        action="store_true",
        help="opt in to live verification for THIS run only (never persisted)",
    )
    run_parser.add_argument(
        "--authorize-write",
        action="append",
        default=[],
        metavar="CAPABILITY_ID",
        help="explicitly authorize live calls for one write capability in THIS run; repeat as needed",
    )
    run_parser.set_defaults(handler=cmd_run)

    status_parser = subparsers.add_parser(
        "status", help="print stage status, durations and delivery rollup"
    )
    add_common(status_parser)
    status_parser.set_defaults(handler=cmd_status)

    diagnose_parser = subparsers.add_parser(
        "diagnose", help="root-cause-first validation diagnostics"
    )
    add_common(diagnose_parser)
    diagnose_parser.add_argument(
        "--stage", choices=sorted(STAGE_CATEGORY_MAP), default=None
    )
    diagnose_parser.add_argument("--capability", default=None)
    diagnose_parser.add_argument("--max-errors", type=int, default=10)
    diagnose_parser.add_argument("--full", action="store_true")
    diagnose_parser.set_defaults(handler=cmd_diagnose)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if declared_core_profile(args.candidate.resolve()) == "core-export-v1":
            raise PipelineError(
                "core-export-v1 uses validate_core_export.py and cannot enter the "
                "strict audit pipeline; generate strict-export-v1 in a separate directory"
            )
        return args.handler(args)
    except PipelineError as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
