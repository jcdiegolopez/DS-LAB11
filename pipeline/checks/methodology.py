from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.checks.common import CheckSpec, frames, result
from pipeline.config import Config
from pipeline.contracts import CheckResult

SPEC = CheckSpec(
    name="methodology",
    verifies="The monthly series comes from the monthly file, not the daily one; no row adds up "
             "subdestinations; stay is derivable as dias_persona / visitantes",
    warns_when="Never",
    stops_when="Any of the three rules is violated",
)

AGGREGATE_LABELS = {"total", "peten", "petén", "todos", "all"}
STAY_TOLERANCE = 0.01


def check(cfg: Config, raw) -> CheckResult:
    mobility, _ = frames(raw)
    errors: list[str] = []

    source = cfg.sources.mobility.file.lower()
    if "diario" in source or "daily" in source:
        errors.append(f"monthly series configured from the daily file '{cfg.sources.mobility.file}'")
    days = pd.to_datetime(mobility["fecha"], errors="coerce").dropna()
    if (days.dt.day != 1).any():
        errors.append(f"{int((days.dt.day != 1).sum())} rows are not monthly (fecha is not the 1st)")

    destinations = set(mobility["destino"].dropna().astype(str).str.strip())
    aggregates = sorted(d for d in destinations if d.lower() in AGGREGATE_LABELS or d.lower().startswith("total"))
    if aggregates:
        errors.append(f"aggregate destination rows present: {', '.join(aggregates)}")
    unknown = sorted(destinations - set(cfg.target.subdestinations) - set(aggregates))
    if unknown:
        errors.append(f"destinations outside the configured subdestinations: {', '.join(unknown)}")

    # Averaging permanencia_prom across rows weights small segments like large ones, so stay is
    # always recomputed from the totals; the column must agree with that ratio row by row.
    if "permanencia_prom" in mobility.columns:
        rows = mobility[(mobility["visitantes"] > 0) & mobility["permanencia_prom"].notna()]
        derived = rows["dias_persona"] / rows["visitantes"]
        off = ~np.isclose(derived, rows["permanencia_prom"], rtol=STAY_TOLERANCE)
        if off.any():
            errors.append(f"{int(off.sum())} rows where permanencia_prom != dias_persona / visitantes")

    return result(SPEC.name, errors, [], "monthly source, no aggregate rows, stay derivable from totals")
