from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from pipeline.config import Config
from pipeline.contracts import PipelineState
from pipeline.stages.preparation import PreparedData


@dataclass(frozen=True)
class FactorModel:
    """Share of the monthly migration entries seen in each subdestination."""

    method: str
    train_months: tuple[str, ...]
    factors: pd.Series

    def predict(self, migration: pd.Series, months: list[str]) -> pd.DataFrame:
        entries = migration.reindex(months)
        values = np.outer(entries.to_numpy(), self.factors.to_numpy())
        return pd.DataFrame(values, index=entries.index, columns=self.factors.index)


def fit_factors(data: PreparedData, months: list[str], method: str) -> FactorModel:
    """Fit on ``months`` only, so the same call serves the growing-window evaluation."""
    if not months:
        raise ValueError("no months to fit the factor")
    visitors = data.visitors.reindex(months)
    entries = data.migration.reindex(months)
    if visitors.isna().any().any() or entries.isna().any():
        raise ValueError(f"fit months without both mobility and migration: {months}")

    if method == "ratio_of_sums":
        factors = visitors.sum() / entries.sum()
    elif method == "mean_of_ratios":
        factors = visitors.div(entries, axis=0).mean()
    else:
        raise ValueError(f"unknown factor method '{method}'")
    return FactorModel(method=method, train_months=tuple(months), factors=factors.rename("factor"))


def training_months(data: PreparedData) -> list[str]:
    return [m for m in data.observed_months() if pd.notna(data.migration.get(m))]


def run(cfg: Config, state: PipelineState) -> None:
    data: PreparedData = state.prepared
    state.model = fit_factors(data, training_months(data), cfg.model_params.factor_method)
