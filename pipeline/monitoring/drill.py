"""Controlled failure drill.

1. Copies the sources and damages the copy (missing column, duplicated key or zero denominator).
2. Runs the pipeline on the damaged copy and checks that a critical quality check stops it.
3. Checks that the approved version is still the current one and that its files are intact.
4. Runs again on the original sources (the correction) and checks that validation passes.
5. Writes the evidence to ``evidence/fault_drill_<mode>_<timestamp>.md``.

    python -m pipeline.monitoring.drill --mode duplicate_key

The damaged copy lives in ``runs/drill-<timestamp>/data`` and the original files are never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd
import yaml

from pipeline.checks.common import TRAVELERS, used_migration
from pipeline.config import Config, load_config
from pipeline.monitoring.log import RUN_LOG_JSON, read_history
from pipeline.publish.store import ESTIMATES_FILE, META_FILE, current_version

# mode -> (source that gets damaged, check expected to stop the run)
MODES = {
    "missing_column": ("mobility", "columns_types"),
    "duplicate_key": ("mobility", "uniqueness"),
    "zero_denominator": ("migration", "values_denominators"),
}


def drop_column(mobility: pd.DataFrame, column: str = "pais") -> pd.DataFrame:
    return mobility.drop(columns=[column])


def duplicate_key(mobility: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([mobility, mobility.iloc[[0]]], ignore_index=True)


def zero_denominator(cfg: Config, migration: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    month = cfg.coverage.months_to_estimate[0]
    periods = used_migration(cfg, migration)["period"]
    damaged = migration.copy()
    damaged.loc[periods[periods == month].index, TRAVELERS] = 0
    return damaged, month


def _read(path: Path, sheet: str) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        return pd.read_excel(path, sheet_name=sheet)


def damage_copy(cfg: Config, mode: str, target_dir: Path) -> str:
    """Copy both sources into ``target_dir`` and damage one of them. Returns what was done."""
    target_dir.mkdir(parents=True, exist_ok=True)
    sources = {"mobility": cfg.sources.mobility, "migration": cfg.sources.migration}
    damaged_source, _ = MODES[mode]
    for role, source in sources.items():
        if role != damaged_source:
            shutil.copy2(cfg.paths.data_dir / source.file, target_dir / source.file)

    source = sources[damaged_source]
    frame = _read(cfg.paths.data_dir / source.file, source.sheet)
    if mode == "missing_column":
        frame, description = drop_column(frame), "column 'pais' removed from the mobility sheet"
    elif mode == "duplicate_key":
        frame, description = duplicate_key(frame), "first mobility row duplicated (repeated key)"
    else:
        frame, month = zero_denominator(cfg, frame)
        description = f"migration travelers set to 0 for {month} (factor denominator)"
    frame.to_excel(target_dir / source.file, sheet_name=source.sheet, index=False)
    return description


def approved_digest(approved_dir: Path, version: str | None) -> str | None:
    if version is None:
        return None
    digest = hashlib.sha256()
    for name in (ESTIMATES_FILE, META_FILE):
        digest.update((approved_dir / version / name).read_bytes())
    return digest.hexdigest()


def _config_with_data_dir(config_path: Path, data_dir: Path, out: Path) -> Path:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["paths"]["data_dir"] = str(data_dir)
    out.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out


def _last_run(cfg: Config) -> dict:
    runs = [e for e in read_history(cfg) if e.get("event") == "run"]
    if not runs:
        raise RuntimeError("the pipeline left no entry in the monitoring log")
    return runs[-1]


def _run_log(cfg: Config, run_id: str) -> dict:
    return json.loads((cfg.paths.work_dir / run_id / RUN_LOG_JSON).read_text(encoding="utf-8"))


def run_drill(
    config_path: Path,
    mode: str,
    run_pipeline: Callable[[list[str]], int] | None = None,
    evidence_dir: Path = Path("evidence"),
) -> dict:
    if run_pipeline is None:
        from pipeline.run import main as run_pipeline

    cfg = load_config(config_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workspace = cfg.paths.work_dir / f"drill-{stamp}"
    _, expected_check = MODES[mode]

    approved = cfg.paths.approved_dir
    before = current_version(approved)
    digest_before = approved_digest(approved, before)

    description = damage_copy(cfg, mode, workspace / "data")
    damaged_config = _config_with_data_dir(config_path, workspace / "data", workspace / "config.yaml")

    damaged_exit = run_pipeline(["--config", str(damaged_config)])
    damaged = _run_log(cfg, _last_run(cfg)["run_id"])
    after_damage = current_version(approved)
    digest_after = approved_digest(approved, after_damage)

    fixed_exit = run_pipeline(["--config", str(config_path)])
    fixed = _run_log(cfg, _last_run(cfg)["run_id"])

    report = {
        "mode": mode,
        "damage": description,
        "expected_check": expected_check,
        "damaged_run": {
            "run_id": damaged["run_id"],
            "exit_code": damaged_exit,
            "status": damaged["status"],
            "blocking_checks": damaged["checks"]["blocking"],
            "stages": [(s["name"], s["outcome"]) for s in damaged["stages"]],
        },
        "approved": {
            "before": before,
            "after_damaged_run": after_damage,
            "pointer_unchanged": before == after_damage,
            "files_unchanged": digest_before == digest_after,
        },
        "fixed_run": {
            "run_id": fixed["run_id"],
            "exit_code": fixed_exit,
            "status": fixed["status"],
            "blocking_checks": fixed["checks"]["blocking"],
            "stages": [(s["name"], s["outcome"]) for s in fixed["stages"]],
            "errors": fixed["errors"],
            "published": fixed["publication"]["published"],
            "approved_after": fixed["publication"]["approved_after"],
        },
    }
    report["detected"] = damaged["status"] == "failed_checks" and expected_check in damaged["checks"]["blocking"]
    report["approved_preserved"] = report["approved"]["pointer_unchanged"] and report["approved"]["files_unchanged"]
    report["recovered_validation"] = not fixed["checks"]["blocking"] and any(
        name == "validate" and outcome == "ok" for name, outcome in report["fixed_run"]["stages"]
    )

    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / f"fault_drill_{mode}_{stamp}.md"
    path.write_text(render(report), encoding="utf-8")
    report["evidence_file"] = str(path)
    return report


def _yes(flag: bool) -> str:
    return "yes" if flag else "**NO**"


def render(report: dict) -> str:
    d, a, f = report["damaged_run"], report["approved"], report["fixed_run"]
    stages = lambda run: ", ".join(f"{n} ({o})" for n, o in run["stages"])  # noqa: E731
    lines = [
        f"# Controlled failure drill: `{report['mode']}`",
        "",
        f"Damage applied to a copy of the sources: {report['damage']}. The original files were not modified.",
        "",
        "| Step | Result |",
        "|---|---|",
        f"| Damaged run | `{d['run_id']}`, exit code {d['exit_code']}, status `{d['status']}` |",
        f"| Stages | {stages(d)} |",
        f"| Checks that stopped it | {', '.join(d['blocking_checks']) or 'none'} (expected `{report['expected_check']}`) |",
        f"| Failure detected | {_yes(report['detected'])} |",
        f"| Approved version before / after | `{a['before']}` / `{a['after_damaged_run']}` |",
        f"| Pointer unchanged | {_yes(a['pointer_unchanged'])} |",
        f"| Approved files unchanged | {_yes(a['files_unchanged'])} |",
        f"| Corrected run (original sources) | `{f['run_id']}`, exit code {f['exit_code']}, status `{f['status']}` |",
        f"| Stages | {stages(f)} |",
        f"| Validation passes after the correction | {_yes(report['recovered_validation'])} |",
        f"| Corrected run published | {'yes' if f['published'] else 'no'}; approved version now `{f['approved_after']}` |",
    ]
    if f["errors"]:
        lines += ["", "Errors of the corrected run:", ""] + [f"- {e}" for e in f["errors"]]
    lines += [
        "",
        "The full logs are in `runs/<run_id>/run_log.md` and `quality_report.md`, and both runs are in MLflow.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.monitoring.drill")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--mode", choices=sorted(MODES), default="duplicate_key")
    parser.add_argument("--evidence-dir", type=Path, default=Path("evidence"))
    args = parser.parse_args(argv)

    report = run_drill(args.config, args.mode, evidence_dir=args.evidence_dir)
    print(f"evidence: {report['evidence_file']}")
    print(f"detected={report['detected']} approved_preserved={report['approved_preserved']} "
          f"recovered_validation={report['recovered_validation']}")
    ok = report["detected"] and report["approved_preserved"] and report["recovered_validation"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
