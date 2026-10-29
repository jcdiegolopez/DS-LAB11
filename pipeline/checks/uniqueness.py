from __future__ import annotations

from pipeline.checks.common import MOBILITY_KEY, CheckSpec, frames, result
from pipeline.config import Config
from pipeline.contracts import CheckResult

SPEC = CheckSpec(
    name="uniqueness",
    verifies="The mobility key destino + fecha + pais + es_consecutivo is unique",
    warns_when="Never",
    stops_when="Any duplicated key",
)


def check(cfg: Config, raw) -> CheckResult:
    mobility, _ = frames(raw)
    duplicated = mobility.duplicated(subset=MOBILITY_KEY, keep=False)
    errors = []
    if duplicated.any():
        sample = mobility.loc[duplicated, MOBILITY_KEY].drop_duplicates().head(3)
        examples = "; ".join(" | ".join(str(v) for v in row) for row in sample.itertuples(index=False))
        errors.append(f"{int(duplicated.sum())} rows share a key, e.g. {examples}")
    return result(SPEC.name, errors, [], f"{len(mobility)} rows, no duplicated keys")
