from __future__ import annotations

import numpy as np

from pipeline.checks.common import (
    TRAVELERS, CheckSpec, foreign_rows, frames, months_using_migration, result, short_list, used_migration,
)
from pipeline.config import Config
from pipeline.contracts import CheckResult

SPEC = CheckSpec(
    name="values_denominators",
    verifies="'visitantes' and 'dias_persona' are finite and non-negative; monthly migration "
             "(the factor denominator) is finite and positive in every used month",
    warns_when="Isolated rows with visitantes = 0",
    stops_when="A negative or non-finite value, or zero / non-finite migration in a used month",
)


def check(cfg: Config, raw) -> CheckResult:
    mobility, migration = frames(raw)
    errors: list[str] = []
    warnings: list[str] = []

    for column in ("visitantes", "dias_persona"):
        values = mobility[column].dropna().astype(float)
        non_finite = int((~np.isfinite(values)).sum())
        negative = int((values < 0).sum())
        if non_finite:
            errors.append(f"mobility: {non_finite} non-finite '{column}'")
        if negative:
            errors.append(f"mobility: {negative} negative '{column}'")

    zeros = int((mobility["visitantes"] == 0).sum())
    if zeros:
        in_segment = int((foreign_rows(cfg, mobility)["visitantes"] == 0).sum())
        warnings.append(f"mobility: {zeros} rows with visitantes = 0 ({in_segment} in the estimated segment)")

    totals = used_migration(cfg, migration).groupby("period")[TRAVELERS].sum(min_count=1)
    used = [m for m in months_using_migration(cfg) if m in totals.index]
    bad = [m for m in used if not np.isfinite(totals[m]) or totals[m] <= 0]
    if bad:
        errors.append(f"migration: zero or non-finite denominator in {short_list(bad)}")

    return result(SPEC.name, errors, warnings, "values finite and denominators positive")
