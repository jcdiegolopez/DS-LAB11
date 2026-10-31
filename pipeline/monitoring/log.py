"""Per-run log: start, end, stages, warnings, errors, publication result and monitors.

Each run writes ``runs/<run_id>/run_log.json`` and ``run_log.md``, and appends one line to
``runs/monitoring_log.jsonl``. That history is what the quality monitor compares against and
also records every restore of an approved version.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from pipeline.config import Config
from pipeline.contracts import CheckStatus, PipelineState, RunStatus
from pipeline.monitoring import monitors
from pipeline.publish.store import current_version
from pipeline.serialization import to_json, to_plain

RUN_LOG_JSON = "run_log.json"
RUN_LOG_MD = "run_log.md"
HISTORY_FILE = "monitoring_log.jsonl"

Stage = Callable[[Config, PipelineState], None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


@dataclass
class StageRecord:
    name: str
    started_at: str
    finished_at: str
    seconds: float
    outcome: str  # ok, blocked (a critical check failed) or failed (the stage raised)
    error: str | None = None


def history_path(cfg: Config) -> Path:
    return cfg.paths.work_dir / HISTORY_FILE


def read_history(cfg: Config) -> list[dict]:
    path = history_path(cfg)
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a line cut by a crash must not hide the rest of the history
    return entries


def append_history(cfg: Config, entry: dict) -> None:
    path = history_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def log_restore(cfg: Config, previous: str | None, restored: str) -> None:
    append_history(cfg, {"event": "restore", "at": _iso(_now()), "from": previous, "to": restored})


class RunMonitor:
    """Times each stage and, once the run ends, runs the monitors and writes the log."""

    def __init__(self, cfg: Config, loader: Callable[[str], Stage]):
        self.loader = loader
        self.stages: list[StageRecord] = []
        self.approved_before = current_version(cfg.paths.approved_dir)
        runs = [e for e in read_history(cfg) if e.get("event") == "run"]
        self.previous_run = runs[-1] if runs else None
        profiled = [e for e in runs if e.get("quality_profile")]
        self.previous_profile = (profiled[-1]["run_id"], profiled[-1]["quality_profile"]) if profiled else None

    def instrument(self, plan: Sequence[tuple[str, Stage | str]]) -> list[tuple[str, Stage]]:
        return [(name, self._timed(name, stage)) for name, stage in plan]

    def _timed(self, name: str, stage: Stage | str) -> Stage:
        def timed(cfg: Config, state: PipelineState) -> None:
            started, clock = _now(), time.perf_counter()
            outcome, error = "failed", None
            try:
                fn = self.loader(stage) if isinstance(stage, str) else stage
                fn(cfg, state)
                outcome = "blocked" if any(r.blocks_pipeline for r in state.check_results) else "ok"
            except Exception as exc:
                error = str(exc)
                raise
            finally:
                self.stages.append(
                    StageRecord(name, _iso(started), _iso(_now()), round(time.perf_counter() - clock, 3), outcome, error)
                )
        return timed

    def run_monitors(self, cfg: Config, state: PipelineState, profile: dict | None) -> list[monitors.MonitorResult]:
        meta, estimates = monitors.read_approved(cfg.paths.approved_dir, self.approved_before)
        previous_approved = (self.approved_before, estimates) if estimates is not None else None
        return [
            monitors.freshness(cfg, state, self.previous_run, meta),
            monitors.quality(cfg, profile, self.previous_profile),
            monitors.results(cfg, state, previous_approved),
        ]

    def finish(self, cfg: Config, state: PipelineState) -> dict:
        profile = monitors.quality_profile(cfg, state.raw)
        results = self.run_monitors(cfg, state, profile)
        state.alerts.extend(f"{r.name}: {a}" for r in results for a in r.alerts)

        log = build_log(cfg, state, self.stages, results, self.approved_before)
        write_log(log, state.context.work_dir)
        append_history(cfg, history_entry(log, state, profile))
        return log


def _publication(cfg: Config, state: PipelineState, approved_before: str | None) -> dict:
    approved_after = current_version(cfg.paths.approved_dir)
    if state.published:
        reason = "published as the new approved version"
    elif state.status is RunStatus.REJECTED:
        reason = "not published: the acceptance rule did not authorize it"
    elif state.status is RunStatus.FAILED_CHECKS:
        reason = "not published: a critical quality check failed"
    elif state.status is RunStatus.FAILED:
        reason = "not published: the run stopped with an error"
    else:
        reason = "not published: the run had no publish stage"
    return {
        "published": state.published,
        "version_dir": str(state.published_dir) if state.published_dir else None,
        "approved_before": approved_before,
        "approved_after": approved_after,
        "approved_unchanged": approved_before == approved_after,
        "approved_available": approved_after is not None,
        "reason": reason,
    }


def build_log(
    cfg: Config,
    state: PipelineState,
    stages: list[StageRecord],
    results: list[monitors.MonitorResult],
    approved_before: str | None,
) -> dict:
    finished = _now()
    started = state.context.started_at
    checks = state.check_results
    return {
        "run_id": state.context.run_id,
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "seconds": round((finished - started).total_seconds(), 3),
        "status": state.status.value,
        "git_commit": state.context.git_commit,
        "source_fingerprint": state.source_fingerprint,
        "stages": [asdict(s) for s in stages],
        "checks": {
            "counts": {s.value: sum(r.status is s for r in checks) for s in CheckStatus} if checks else {},
            "blocking": [r.name for r in checks if r.blocks_pipeline],
        },
        "warnings": list(state.warnings),
        "errors": list(state.errors),
        "publication": _publication(cfg, state, approved_before),
        "monitors": [to_plain(asdict(r)) for r in results],
        "alerts": list(state.alerts),
    }


def history_entry(log: dict, state: PipelineState, profile: dict | None) -> dict:
    return {
        "event": "run",
        "run_id": log["run_id"],
        "started_at": log["started_at"],
        "finished_at": log["finished_at"],
        "status": log["status"],
        "published": log["publication"]["published"],
        "approved_after": log["publication"]["approved_after"],
        "source_fingerprint": state.source_fingerprint,
        "warnings": len(log["warnings"]),
        "errors": len(log["errors"]),
        "alerts": len(log["alerts"]),
        "quality_profile": profile,
    }


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_markdown(log: dict) -> str:
    pub = log["publication"]
    lines = [
        f"# Run log `{log['run_id']}`",
        "",
        f"- Status: **{log['status']}**",
        f"- Started {log['started_at']}, finished {log['finished_at']} ({log['seconds']} s)",
        f"- Commit `{log['git_commit']}`",
        f"- Publication: {pub['reason']}",
        f"- Approved version before: `{pub['approved_before']}`, after: `{pub['approved_after']}`",
        "",
        "## Stages",
        "",
        "| Stage | Outcome | Seconds | Error |",
        "|---|---|---|---|",
    ]
    lines += [f"| {s['name']} | {s['outcome']} | {s['seconds']} | {_cell(s['error'] or '')} |" for s in log["stages"]]
    lines += ["", "## Monitors", "", "| Monitor | Status | Detail |", "|---|---|---|"]
    lines += [f"| {m['name']} | {m['status']} | {_cell(m['detail'])} |" for m in log["monitors"]]
    for title, items in (("Alerts", log["alerts"]), ("Warnings", log["warnings"]), ("Errors", log["errors"])):
        if items:
            lines += ["", f"## {title}", ""] + [f"- {_cell(i)}" for i in items]
    return "\n".join(lines) + "\n"


def write_log(log: dict, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / RUN_LOG_JSON).write_text(to_json(log), encoding="utf-8")
    (directory / RUN_LOG_MD).write_text(render_markdown(log), encoding="utf-8")
