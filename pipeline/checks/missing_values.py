from __future__ import annotations

from pipeline.checks.common import TRAVELERS, CheckSpec, frames, months_using_migration, result, short_list, used_migration
from pipeline.config import Config
from pipeline.contracts import CheckResult

SPEC = CheckSpec(
    name="missing_values",
    verifies="Nulls in 'visitantes', 'pais' and 'permanencia_prom', and migration present for every "
             "month it is used in (factor months and months to estimate)",
    warns_when="Nulls in 'pais' or 'permanencia_prom' at or below thresholds.max_missing_ratio",
    stops_when="Any null 'visitantes', tolerated nulls above the threshold, or migration missing "
               "for a used month",
)

TOLERATED = ("pais", "permanencia_prom")


def check(cfg: Config, raw) -> CheckResult:
    mobility, migration = frames(raw)
    limit = cfg.thresholds.max_missing_ratio
    errors: list[str] = []
    warnings: list[str] = []

    null_visitors = int(mobility["visitantes"].isna().sum())
    if null_visitors:
        errors.append(f"mobility: {null_visitors} rows with null visitantes")

    for column in TOLERATED:
        if column not in mobility.columns:
            continue
        nulls = int(mobility[column].isna().sum())
        if nulls:
            ratio = nulls / len(mobility)
            message = f"mobility: {nulls} null '{column}' ({ratio:.2%}, limit {limit:.2%})"
            (errors if ratio > limit else warnings).append(message)

    rows = used_migration(cfg, migration)
    used = months_using_migration(cfg)
    present = set(rows["period"].dropna())
    absent = [m for m in used if m not in present]
    null_months = sorted(set(rows.loc[rows[TRAVELERS].isna(), "period"].dropna()) & set(used))
    if absent:
        errors.append(f"migration: no rows for used months {short_list(absent)}")
    if null_months:
        errors.append(f"migration: null travelers in used months {short_list(null_months)}")

    return result(SPEC.name, errors, warnings, "no missing values in the columns used")
