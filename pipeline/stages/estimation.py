from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from pipeline.config import Config
from pipeline.contracts import PipelineState
from pipeline.stages.fitting import FactorModel
from pipeline.stages.preparation import PreparedData

ESTIMATES_FILE = "estimates.csv"
COLUMNS = [
    "target", "subdestination", "period", "value", "unit", "kind",
    "run_id", "generated_at", "procedure_version",
]


def _long(table: pd.DataFrame, kind: str) -> pd.DataFrame:
    stacked = table.rename_axis(index="period", columns="subdestination").stack(future_stack=True)
    return stacked.rename("value").reset_index().assign(kind=kind)


def build_estimates(cfg: Config, data: PreparedData, model: FactorModel, run_id: str) -> pd.DataFrame:
    observed = data.visitors.loc[data.observed_months()]
    estimated = model.predict(data.migration, cfg.coverage.months_to_estimate)
    rows = pd.concat([_long(observed, "observed"), _long(estimated, "estimated")], ignore_index=True)
    rows = rows.assign(
        target=cfg.target.name,
        unit=cfg.target.unit,
        run_id=run_id,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        procedure_version=cfg.procedure_version,
    )
    rank = rows["subdestination"].map({name: i for i, name in enumerate(cfg.target.subdestinations)})
    rows = rows.assign(_rank=rank).sort_values(["_rank", "period"])
    return rows[COLUMNS].reset_index(drop=True)


def run(cfg: Config, state: PipelineState) -> None:
    estimates = build_estimates(cfg, state.prepared, state.model, state.context.run_id)
    # a month without data stays an empty cell, never zero
    estimates.to_csv(state.context.work_dir / ESTIMATES_FILE, index=False, na_rep="")
    state.estimates = estimates
