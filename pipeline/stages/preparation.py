from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pipeline.checks.common import TRAVELERS, foreign_rows, frames, month_labels, month_range, used_migration
from pipeline.config import Config
from pipeline.contracts import PipelineState


@dataclass(frozen=True)
class PreparedData:
    """Monthly series indexed by 'YYYY-MM'.

    ``visitors`` has one column per subdestination; months without phone coverage stay NaN.
    ``migration`` holds the monthly entries of the configured visitor types.
    """

    visitors: pd.DataFrame
    migration: pd.Series

    def observed_months(self) -> list[str]:
        return [m for m in self.visitors.index if self.visitors.loc[m].notna().all()]


def visitor_series(cfg: Config, mobility: pd.DataFrame) -> pd.DataFrame:
    # Rows split one subdestination-month by country and stay length, so adding them counts
    # each person once. Subdestinations are never added together: people overlap between them.
    rows = foreign_rows(cfg, mobility)
    rows = rows[rows["destino"].isin(cfg.target.subdestinations)]
    rows = rows.assign(period=month_labels(rows["anio"], rows["mes"]))
    table = rows.pivot_table(index="period", columns="destino", values="visitantes", aggfunc="sum")

    months = cfg.coverage.mobility_months + cfg.coverage.months_to_estimate
    table = table.reindex(index=month_range(min(months), max(months)), columns=cfg.target.subdestinations)
    table.index.name, table.columns.name = "period", None
    return table


def migration_series(cfg: Config, migration: pd.DataFrame) -> pd.Series:
    totals = used_migration(cfg, migration).groupby("period")[TRAVELERS].sum(min_count=1)
    index = month_range(cfg.coverage.migration_first_period, cfg.coverage.expected_last_period.migration)
    series = totals.reindex(index)
    series.index.name = "period"
    return series.rename("migration")


def prepare(cfg: Config, raw) -> PreparedData:
    mobility, migration = frames(raw)
    return PreparedData(visitors=visitor_series(cfg, mobility), migration=migration_series(cfg, migration))


def run(cfg: Config, state: PipelineState) -> None:
    state.prepared = prepare(cfg, state.raw)
