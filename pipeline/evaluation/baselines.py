"""Simple references the factor model is compared against.

Each one uses only observed months strictly before the month it predicts.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd


def _prior(series: pd.Series, month: str) -> pd.Series:
    return series[series.index < month].dropna()


def last_observed(series: pd.Series, month: str) -> float:
    prior = _prior(series, month)
    return float(prior.iloc[-1]) if len(prior) else float("nan")


def prior_mean(series: pd.Series, month: str) -> float:
    prior = _prior(series, month)
    return float(prior.mean()) if len(prior) else float("nan")


BASELINES: dict[str, Callable[[pd.Series, str], float]] = {
    "last_observed": last_observed,
    "prior_mean": prior_mean,
}


def predict(name: str, visitors: pd.DataFrame, months: list[str]) -> pd.DataFrame:
    fn = BASELINES[name]
    values = {col: [fn(visitors[col], m) for m in months] for col in visitors.columns}
    return pd.DataFrame(values, index=pd.Index(months, name="period"))
