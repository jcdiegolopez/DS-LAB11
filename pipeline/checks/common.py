"""Column names and helpers shared by the quality checks.

The checks read ``state.raw`` as a mapping with the original source frames:
``{"mobility": DataFrame, "migration": DataFrame}``, with the column names of the files.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from pipeline.config import Config
from pipeline.contracts import CheckResult, CheckStatus

MOBILITY = "mobility"
MIGRATION = "migration"

MOBILITY_KEY = ["destino", "fecha", "pais", "es_consecutivo"]

YEAR = "Año"
MONTH_CODE = "Mes cod"
VISITOR_TYPE = "Tipo de Viajero"
TRAVELERS = "Viajero"


@dataclass(frozen=True)
class CheckSpec:
    name: str
    verifies: str
    warns_when: str
    stops_when: str


def frames(raw: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not isinstance(raw, Mapping) or MOBILITY not in raw or MIGRATION not in raw:
        raise ValueError("state.raw must hold the 'mobility' and 'migration' frames")
    return raw[MOBILITY], raw[MIGRATION]


def month_labels(years: pd.Series, months: pd.Series) -> pd.Series:
    y = pd.to_numeric(years, errors="coerce")
    m = pd.to_numeric(months, errors="coerce")
    valid = y.notna() & m.between(1, 12)
    labels = pd.Series(None, index=years.index, dtype="object")
    labels[valid] = [f"{int(a):04d}-{int(b):02d}" for a, b in zip(y[valid], m[valid])]
    return labels


def month_range(first: str, last: str) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(first, last, freq="M")]


def used_migration(cfg: Config, migration: pd.DataFrame) -> pd.DataFrame:
    rows = migration[migration[VISITOR_TYPE].isin(cfg.sources.migration.visitor_types)]
    return rows.assign(period=month_labels(rows[YEAR], rows[MONTH_CODE]))


def months_using_migration(cfg: Config) -> list[str]:
    """Months whose migration total enters the factor or an estimate."""
    last = cfg.coverage.expected_last_period.migration
    observed = [m for m in cfg.coverage.mobility_months if m <= last]
    return sorted(set(observed) | set(cfg.coverage.months_to_estimate))


def foreign_rows(cfg: Config, mobility: pd.DataFrame) -> pd.DataFrame:
    return mobility[~mobility["pais"].isin(cfg.target.exclude_countries)]


def short_list(items: list, limit: int = 5) -> str:
    shown = ", ".join(str(i) for i in items[:limit])
    return shown + (f" (+{len(items) - limit} more)" if len(items) > limit else "")


def result(name: str, errors: list[str], warnings: list[str], ok_detail: str) -> CheckResult:
    if errors:
        return CheckResult(name, CheckStatus.ERROR, "; ".join(errors + warnings))
    if warnings:
        return CheckResult(name, CheckStatus.WARNING, "; ".join(warnings))
    return CheckResult(name, CheckStatus.OK, ok_detail)
