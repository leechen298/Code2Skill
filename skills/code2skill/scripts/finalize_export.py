#!/usr/bin/env python3
"""Finalize audit hashes only after real checks and a real live invocation pass."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_root", type=Path)
    parser.add_argument("--verification-report", type=Path, required=True, help="JSON report whose checks all came from executed commands")
    parser.add_argument("--live-input", type=Path, required=True, help="sanitized JSON actually sent to the live MCP call")
    parser.add_argument("--live-result", type=Path, required=True, help="sanitized JSON actually returned by the live MCP call")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.artifact_root.resolve()
    validator = Path(__file__).with_name("validate_artifacts.py")
    before = subprocess.run([sys.executable, str(validator), str(root), "--pre-finalize"], check=False)
    if before.returncode != 0:
        return before.returncode

    try:
        report = read_json(args.verification_report)
        live_input = read_json(args.live_input)
        live_result = read_json(args.live_result)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"ERROR finalization evidence: {error}", file=sys.stderr)
        return 1
    checks = report.get("checks") if isinstance(report, dict) else None
    if report.get("status") != "passed" or not isinstance(checks, list) or not checks or any(not isinstance(item, dict) or item.get("status") != "passed" or not item.get("command") for item in checks):
        print("ERROR verification report must contain executed commands and only passed checks", file=sys.stderr)
        return 1
    if not isinstance(live_result, dict) or live_result.get("isError") is not False:
        print("ERROR live result must be a real successful MCP result with isError=false", file=sys.stderr)
        return 1

    bundle_hash = digest_file(root / "capability-bundle.json")
    draft_hash = digest_file(root / "capability-draft.json")
    write_json(root / "function-core/validation-receipt.json", {
        "schemaVersion": "v1",
        "capabilityDraftHash": draft_hash,
        "bundleHash": bundle_hash,
        "validationStatus": "passed",
    })
    base_hashes = {
        path.relative_to(root).as_posix(): digest_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in {"preflight-report.json", "approval-audit.json", "live-verification.json", "export-manifest.json"}
    }
    write_json(root / "preflight-report.json", {
        "schemaVersion": "v1",
        "status": "passed",
        "capabilityDraftHash": draft_hash,
        "bundleHash": bundle_hash,
        "generatedArtifactHashes": base_hashes,
        "checks": checks,
    })
    write_json(root / "live-verification.json", {
        "schemaVersion": "v1",
        "status": "passed",
        "isError": False,
        "inputHash": digest_bytes(json.dumps(live_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()),
        "resultHash": digest_bytes(json.dumps(live_result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()),
    })
    approved = {
        path.relative_to(root).as_posix(): digest_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in {"approval-audit.json", "export-manifest.json"}
    }
    write_json(root / "approval-audit.json", {
        "schemaVersion": "v1",
        "decision": "approved",
        "preflightStatus": "passed",
        "artifacts": [{"relativePath": path, "sha256": value} for path, value in approved.items()],
    })
    manifest_files = [
        {"relativePath": path.relative_to(root).as_posix(), "sha256": digest_file(path), "sanitized": True}
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "export-manifest.json"
    ]
    write_json(root / "export-manifest.json", {"schemaVersion": "v0", "files": manifest_files})
    return subprocess.run([sys.executable, str(validator), str(root)], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
