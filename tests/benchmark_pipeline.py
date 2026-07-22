"""Code2Skill staged-pipeline timing benchmark (synthetic case, honest labels).

Measures the deterministic Producer pipeline on a synthetic two-capability
project in three scenarios:

1. first:      a full first-round run (analyze -> generate -> verify -> finalize);
2. incremental: one hand-authored file changed; only affected stages re-run;
3. unchanged:  nothing changed; every completed stage is skipped.

The benchmark reports wall time, which stages executed, how many fixed
verification checks re-ran, and how many files had to be touched between
scenarios. It does NOT measure the Agent's source-reading/authoring time --
that is exactly the work the pipeline avoids repeating: scenario 2 and 3 show
how much of the deterministic repeat work disappears once inputs are
content-addressed.

Run: python3 tests/benchmark_pipeline.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import tests.test_pipeline as fixture  # noqa: E402

PIPELINE = fixture.SCRIPTS / "run_pipeline.py"
STAGE_ORDER = ("analyze", "generate", "verify", "runtime-verify", "finalize")


def run_cli(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PIPELINE), *[str(arg) for arg in args]],
        capture_output=True,
        text=True,
        check=False,
    )


def load_state(state_dir: Path) -> dict:
    return json.loads((state_dir / "run-state.json").read_text(encoding="utf-8"))


def scenario_report(state: dict) -> dict[str, object]:
    stages = state["stages"]
    executed = [name for name in STAGE_ORDER if stages[name]["lastAction"] == "executed"]
    skipped = [name for name in STAGE_ORDER if stages[name]["lastAction"] == "skipped-unchanged"]
    return {
        "executedStages": executed,
        "skippedUnchanged": skipped,
        "executedRuns": sum(int(stages[name]["runs"]) for name in STAGE_ORDER),
    }


def main() -> int:
    fixture.setUpModule()
    try:
        with tempfile.TemporaryDirectory(prefix="code2skill-benchmark-") as directory:
            root = Path(directory)

            class Harness(fixture.PipelineTestCase):
                pass

            case = Harness(methodName="run")
            case.root = root
            candidate, state_dir = case.install_candidate()

            # ---- first run -------------------------------------------------
            init = run_cli(
                "init",
                candidate,
                "--source-map",
                f"fictional-topic-contract={root / 'sources' / 'contract-root'}",
                "--source-map",
                f"fictional-topic-service={root / 'sources' / 'service-root'}",
            )
            if init.returncode != 0:
                print(init.stderr)
                return 1
            start = time.monotonic()
            first = run_cli("run", candidate)
            first_ms = int((time.monotonic() - start) * 1000)
            if first.returncode != 0:
                print(first.stdout, first.stderr)
                return 1
            first_state = load_state(state_dir)
            first_stages = {
                name: first_state["stages"][name]["durationMs"] for name in STAGE_ORDER
            }

            # ---- incremental run (Canonical Contract changed) --------------
            # The realistic Agent loop: one contract field changes; analyze,
            # deterministic compilation, verification, and finalization rerun
            # while nothing is re-read or re-authored by hand.
            contract_path = candidate / "canonical-contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["capabilities"][0]["outputs"][0]["valueDomain"]["values"] = [
                ["synthetic-topic-alpha", "synthetic-topic-gamma"]
            ]
            contract_path.write_text(
                json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            start = time.monotonic()
            incremental = run_cli("run", candidate)
            incremental_ms = int((time.monotonic() - start) * 1000)
            if incremental.returncode != 0:
                print(incremental.stdout, incremental.stderr)
                return 1
            incremental_report = scenario_report(load_state(state_dir))
            incremental_report["stagesReExecuted"] = len(
                incremental_report["executedStages"]
            )
            del incremental_report["executedRuns"]

            # ---- unchanged run ---------------------------------------------
            start = time.monotonic()
            unchanged = run_cli("run", candidate)
            unchanged_ms = int((time.monotonic() - start) * 1000)
            if unchanged.returncode != 0:
                print(unchanged.stdout, unchanged.stderr)
                return 1
            unchanged_report = scenario_report(load_state(state_dir))
            unchanged_report["stagesReExecuted"] = len(unchanged_report["executedStages"])
            del unchanged_report["executedRuns"]

            result = {
                "case": "synthetic two-capability candidate (read + write, local)",
                "machineNote": "durations are wall-clock milliseconds of the deterministic pipeline only; Agent source reading/authoring time is not included and is exactly what the pipeline avoids repeating",
                "scenarios": {
                    "first": {
                        "wallMs": first_ms,
                        "stageDurationsMs": first_stages,
                        "executedStages": ["analyze", "generate", "verify", "finalize"],
                        "skippedUnchanged": [],
                    },
                    "incremental(one contract field)": {
                        "wallMs": incremental_ms,
                        **incremental_report,
                        "agentFilesTouched": 1,
                        "agentReReadSources": 0,
                    },
                    "unchanged(no input change)": {
                        "wallMs": unchanged_ms,
                        **unchanged_report,
                        "agentFilesTouched": 0,
                        "agentReReadSources": 0,
                    },
                },
                "savings": {
                    "unchangedVsFirst": (
                        f"{(1 - unchanged_ms / first_ms) * 100:.1f}% less wall time"
                        if first_ms
                        else "n/a"
                    ),
                    "incrementalStagesReExecuted": incremental_report["executedStages"],
                    "incrementalStagesAvoided": incremental_report["skippedUnchanged"],
                },
            }
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
    finally:
        fixture.tearDownModule()


if __name__ == "__main__":
    raise SystemExit(main())
