from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.checks import (
    columns_types, dates_coverage, methodology, missing_values, uniqueness, values_denominators,
)
from pipeline.config import Config
from pipeline.contracts import CheckResult, CheckStatus, PipelineState

CHECKS = (columns_types, dates_coverage, uniqueness, missing_values, values_denominators, methodology)

REPORT_JSON = "quality_report.json"
REPORT_MD = "quality_report.md"


def run_checks(cfg: Config, raw) -> list[CheckResult]:
    results: list[CheckResult] = []
    for module in CHECKS:
        name = module.SPEC.name
        # The other checks index the columns that columns_types guarantees.
        if module is not columns_types and results and results[0].status is CheckStatus.ERROR:
            results.append(CheckResult(name, CheckStatus.ERROR, "not run: columns_types failed"))
            continue
        try:
            results.append(module.check(cfg, raw))
        except Exception as exc:
            results.append(CheckResult(name, CheckStatus.ERROR, f"check crashed: {exc!r}"))
    return results


def build_report(results: list[CheckResult], run_id: str) -> dict:
    specs = {m.SPEC.name: m.SPEC for m in CHECKS}
    return {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "outcome": "blocked" if any(r.blocks_pipeline for r in results) else "passed",
        "checks": [
            {
                "name": r.name,
                "status": r.status.value,
                "critical": r.critical,
                "blocks_pipeline": r.blocks_pipeline,
                "detail": r.detail,
                "verifies": specs[r.name].verifies,
                "warns_when": specs[r.name].warns_when,
                "stops_when": specs[r.name].stops_when,
            }
            for r in results
        ],
    }


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_markdown(report: dict) -> str:
    lines = [
        "# Quality report",
        "",
        f"Run `{report['run_id']}`, generated {report['generated_at']}. Outcome: **{report['outcome']}**.",
        "",
        "| Check | Status | Stops the run | Detail |",
        "|---|---|---|---|",
    ]
    for c in report["checks"]:
        stops = "yes" if c["blocks_pipeline"] else "no"
        lines.append(f"| {c['name']} | {c['status']} | {stops} | {_cell(c['detail'])} |")
    lines += ["", "## Rules", "", "| Check | Verifies | Warns when | Stops when |", "|---|---|---|---|"]
    for c in report["checks"]:
        lines.append(
            f"| {c['name']} | {_cell(c['verifies'])} | {_cell(c['warns_when'])} | {_cell(c['stops_when'])} |"
        )
    return "\n".join(lines) + "\n"


def write_report(report: dict, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    json_path, md_path = directory / REPORT_JSON, directory / REPORT_MD
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def run(cfg: Config, state: PipelineState) -> None:
    results = run_checks(cfg, state.raw)
    state.check_results.extend(results)
    state.warnings.extend(f"{r.name}: {r.detail}" for r in results if r.status is CheckStatus.WARNING)
    write_report(build_report(results, state.context.run_id), state.context.work_dir)
