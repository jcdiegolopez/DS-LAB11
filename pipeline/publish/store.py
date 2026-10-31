from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.contracts import ESTIMATE_COLUMNS, STAMPED_COLUMNS, VALID_KINDS
from pipeline.serialization import to_json

CURRENT_FILE = "current"
ESTIMATES_FILE = "estimates.csv"
META_FILE = "meta.json"
PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
KEY_COLUMNS = ["target", "subdestination", "period"]


def validate_estimates(estimates: pd.DataFrame) -> None:
    missing = [c for c in ESTIMATE_COLUMNS if c not in estimates.columns]
    if missing:
        raise ValueError(f"estimates are missing columns: {missing}")
    if estimates.empty:
        raise ValueError("estimates are empty")

    kinds = estimates["kind"]
    if kinds.isna().any() or not set(kinds) <= VALID_KINDS:
        raise ValueError(f"kind must be one of {sorted(VALID_KINDS)}")

    bad_periods = sorted({str(p) for p in estimates["period"] if not PERIOD_PATTERN.match(str(p))})
    if bad_periods:
        raise ValueError(f"periods must look like YYYY-MM, got {bad_periods}")

    value = pd.Series(pd.to_numeric(estimates["value"], errors="coerce"), index=estimates.index)
    if (estimates["value"].notna() & value.isna()).any():
        raise ValueError("value contains non-numeric entries")
    present = value.dropna().to_numpy(dtype=float)
    if not np.isfinite(present).all():
        raise ValueError("value contains non-finite numbers")
    if (present < 0).any():
        raise ValueError("value contains negative numbers")

    if estimates.duplicated(KEY_COLUMNS).any():
        raise ValueError(f"estimates are not unique per {KEY_COLUMNS}")


def stamp(estimates: pd.DataFrame, run_id: str, generated_at: datetime, procedure_version: str) -> pd.DataFrame:
    out = estimates.loc[:, list(ESTIMATE_COLUMNS)].copy()
    out["run_id"] = run_id
    out["generated_at"] = generated_at.isoformat(timespec="seconds")
    out["procedure_version"] = procedure_version
    return out[list(ESTIMATE_COLUMNS + STAMPED_COLUMNS)]


def is_complete(version_dir: Path) -> bool:
    return (version_dir / ESTIMATES_FILE).is_file() and (version_dir / META_FILE).is_file()


def list_versions(approved_dir: Path) -> list[str]:
    if not approved_dir.is_dir():
        return []
    return sorted(
        p.name for p in approved_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".") and is_complete(p)
    )


def current_version(approved_dir: Path) -> str | None:
    pointer = approved_dir / CURRENT_FILE
    if not pointer.is_file():
        return None
    return pointer.read_text(encoding="utf-8").strip() or None


def write_version(approved_dir: Path, run_id: str, estimates: pd.DataFrame, meta: dict) -> Path:
    final = approved_dir / run_id
    if final.exists():
        raise FileExistsError(f"version {run_id} already exists")
    staging = approved_dir / f".staging-{run_id}"
    staging.mkdir(parents=True, exist_ok=False)
    estimates.to_csv(staging / ESTIMATES_FILE, index=False)
    (staging / META_FILE).write_text(to_json(meta), encoding="utf-8")
    staging.rename(final)
    return final


def set_current(approved_dir: Path, run_id: str) -> None:
    tmp = approved_dir / ".current.tmp"
    tmp.write_text(run_id, encoding="utf-8")
    os.replace(tmp, approved_dir / CURRENT_FILE)


def restore(approved_dir: Path, run_id: str) -> None:
    if run_id not in list_versions(approved_dir):
        raise ValueError(f"{run_id} is not a complete approved version in {approved_dir}")
    set_current(approved_dir, run_id)
