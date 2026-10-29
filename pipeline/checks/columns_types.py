from __future__ import annotations

import pandas as pd
from pandas.api import types as ptypes

from pipeline.checks.common import MONTH_CODE, TRAVELERS, VISITOR_TYPE, YEAR, CheckSpec, frames, result
from pipeline.config import Config
from pipeline.contracts import CheckResult

SPEC = CheckSpec(
    name="columns_types",
    verifies="Required columns of both sources are present with compatible types",
    warns_when="An optional column is missing or has an unexpected type",
    stops_when="A required column is missing or its type is incompatible",
)

NUMERIC, TEXT, DATE = "numeric", "text", "date"

MOBILITY_REQUIRED = {
    "destino": TEXT, "sub_grupo": TEXT, "anio": NUMERIC, "mes": NUMERIC,
    "pais": TEXT, "es_consecutivo": TEXT, "fecha": DATE,
    "visitantes": NUMERIC, "dias_persona": NUMERIC,
}
# permanencia_prom is informative only: stay is derived from dias_persona / visitantes
MOBILITY_OPTIONAL = {"permanencia_prom": NUMERIC}
MIGRATION_REQUIRED = {YEAR: NUMERIC, MONTH_CODE: NUMERIC, VISITOR_TYPE: TEXT, TRAVELERS: NUMERIC}


def _compatible(series: pd.Series, kind: str) -> bool:
    if kind == NUMERIC:
        return ptypes.is_numeric_dtype(series) and not ptypes.is_bool_dtype(series)
    if kind == DATE:
        if ptypes.is_datetime64_any_dtype(series):
            return True
        parsed = pd.to_datetime(series, errors="coerce")
        return bool(parsed.notna().sum() == series.notna().sum())
    return ptypes.is_string_dtype(series) or ptypes.is_object_dtype(series)


def _inspect(frame: pd.DataFrame, source: str, schema: dict[str, str]) -> list[str]:
    problems = []
    for column, kind in schema.items():
        if column not in frame.columns:
            problems.append(f"{source}: missing column '{column}'")
        elif not _compatible(frame[column], kind):
            problems.append(f"{source}: column '{column}' is {frame[column].dtype}, expected {kind}")
    return problems


def check(cfg: Config, raw) -> CheckResult:
    mobility, migration = frames(raw)
    errors = _inspect(mobility, "mobility", MOBILITY_REQUIRED) + _inspect(migration, "migration", MIGRATION_REQUIRED)
    warnings = _inspect(mobility, "mobility (optional)", MOBILITY_OPTIONAL)
    return result(SPEC.name, errors, warnings, "all required columns present with compatible types")
