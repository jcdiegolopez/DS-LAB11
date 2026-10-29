from __future__ import annotations

import pandas as pd

from pipeline.checks.common import CheckSpec, frames, month_labels, month_range, result, short_list, used_migration
from pipeline.config import Config
from pipeline.contracts import CheckResult

SPEC = CheckSpec(
    name="dates_coverage",
    verifies="'fecha' agrees with 'anio' and 'mes'; observed months of both sources match the "
             "configured coverage",
    warns_when="The months to estimate are absent from mobility (expected, never filled with zero), "
               "or a month outside the configured coverage appears",
    stops_when="An invalid date, or a month that should have coverage is missing",
)


def _mobility(cfg: Config, mobility: pd.DataFrame, errors: list[str], warnings: list[str]) -> None:
    dates = pd.to_datetime(mobility["fecha"], errors="coerce")
    from_parts = month_labels(mobility["anio"], mobility["mes"])
    invalid = dates.isna() | from_parts.isna()
    if invalid.any():
        errors.append(f"mobility: {int(invalid.sum())} rows with invalid fecha/anio/mes")

    valid = ~invalid
    mismatched = dates[valid].dt.strftime("%Y-%m") != from_parts[valid]
    if mismatched.any():
        errors.append(f"mobility: {int(mismatched.sum())} rows where fecha disagrees with anio/mes")

    observed = set(from_parts[valid])
    expected = set(cfg.coverage.mobility_months)
    to_estimate = set(cfg.coverage.months_to_estimate)

    missing = sorted(expected - observed)
    if missing:
        errors.append(f"mobility: expected months missing: {short_list(missing)}")
    gap = sorted(to_estimate - observed)
    if gap:
        warnings.append(f"mobility: no coverage for {', '.join(gap)} (to be estimated, not filled)")
    filled = sorted(to_estimate & observed)
    if filled:
        warnings.append(f"mobility: data found for months configured as uncovered: {', '.join(filled)}")
    unexpected = sorted(observed - expected - to_estimate)
    if unexpected:
        warnings.append(f"mobility: months outside the configured coverage: {short_list(unexpected)}")


def _migration(cfg: Config, migration: pd.DataFrame, errors: list[str]) -> None:
    periods = used_migration(cfg, migration)["period"]
    if periods.isna().any():
        errors.append(f"migration: {int(periods.isna().sum())} rows with invalid year/month")
    present = set(periods.dropna())
    wanted = month_range(cfg.coverage.migration_first_period, cfg.coverage.expected_last_period.migration)
    missing = [m for m in wanted if m not in present]
    if missing:
        errors.append(f"migration: expected months missing: {short_list(missing)}")


def check(cfg: Config, raw) -> CheckResult:
    mobility, migration = frames(raw)
    errors: list[str] = []
    warnings: list[str] = []
    _mobility(cfg, mobility, errors, warnings)
    _migration(cfg, migration, errors)
    return result(SPEC.name, errors, warnings, "dates consistent and coverage as configured")
