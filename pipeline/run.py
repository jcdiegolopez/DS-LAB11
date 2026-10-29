from __future__ import annotations

import argparse
import importlib
import random
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from pipeline.config import Config, load_config
from pipeline.contracts import PipelineState, RunContext, RunStatus

StageFn = Callable[[Config, PipelineState], None]

DEFAULT_STAGES: tuple[tuple[str, str], ...] = (
    ("read", "pipeline.stages.reading"),
    ("validate", "pipeline.checks.runner"),
    ("prepare", "pipeline.stages.preparation"),
    ("fit", "pipeline.stages.fitting"),
    ("evaluate", "pipeline.evaluation.runner"),
    ("estimate", "pipeline.stages.estimation"),
    ("publish", "pipeline.publish.runner"),
)


def current_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip()


def new_context(cfg: Config) -> RunContext:
    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    work_dir = cfg.paths.work_dir / run_id
    work_dir.mkdir(parents=True, exist_ok=True)
    return RunContext(run_id=run_id, started_at=started, git_commit=current_commit(), work_dir=work_dir)


def load_stage(module_path: str) -> StageFn:
    return importlib.import_module(module_path).run


def execute(
    cfg: Config,
    stages: Sequence[tuple[str, StageFn | str]] | None = None,
) -> PipelineState:
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)

    state = PipelineState(context=new_context(cfg))
    plan = stages if stages is not None else DEFAULT_STAGES

    for name, stage in plan:
        try:
            fn = load_stage(stage) if isinstance(stage, str) else stage
            fn(cfg, state)
        except Exception as exc:
            state.errors.append(f"{name}: {exc}")
            state.status = RunStatus.FAILED
            return state
        state.completed_stages.append(name)
        if any(r.blocks_pipeline for r in state.check_results):
            state.status = RunStatus.FAILED_CHECKS
            return state

    return state


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.run")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args(argv)

    state = execute(load_config(args.config))
    print(f"run_id={state.context.run_id} status={state.status.value}")
    print(f"completed: {', '.join(state.completed_stages) or '-'}")
    for error in state.errors:
        print(f"error: {error}", file=sys.stderr)
    return 0 if state.status is RunStatus.SUCCESS else 1


if __name__ == "__main__":
    raise SystemExit(main())
