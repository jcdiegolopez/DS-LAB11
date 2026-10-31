from datetime import datetime, timezone

import pandas as pd

from pipeline.contracts import PipelineState, RunContext


def make_estimates(value_jan=4464.0) -> pd.DataFrame:
    rows = [
        ("Tikal y Flores (Petén)", "Isla De Flores", "2025-12", 5409.0, "visitors", "observed"),
        ("Tikal y Flores (Petén)", "Isla De Flores", "2026-01", value_jan, "visitors", "estimated"),
        ("Tikal y Flores (Petén)", "Isla De Flores", "2026-02", 3516.0, "visitors", "estimated"),
    ]
    return pd.DataFrame(rows, columns=["target", "subdestination", "period", "value", "unit", "kind"])


def make_state(cfg, run_id="20261030T000000Z-aaaaaa", accepted=True, estimates=None) -> PipelineState:
    work_dir = cfg.paths.work_dir / run_id
    work_dir.mkdir(parents=True, exist_ok=True)
    context = RunContext(
        run_id=run_id,
        started_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
        git_commit="abc1234",
        work_dir=work_dir,
    )
    state = PipelineState(context=context)
    state.estimates = make_estimates() if estimates is None else estimates
    state.accepted = accepted
    state.metrics = {"mae_isla_de_flores": 1606.0}
    state.model = {"Isla De Flores": 0.014846}
    state.source_fingerprint = "a" * 64
    return state
