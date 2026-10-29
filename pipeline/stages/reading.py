from __future__ import annotations

import hashlib
import warnings
from pathlib import Path

import pandas as pd

from pipeline.checks.common import MIGRATION, MOBILITY
from pipeline.config import Config
from pipeline.contracts import PipelineState

CHUNK = 1 << 20


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def source_paths(cfg: Config) -> dict[str, Path]:
    base = cfg.paths.data_dir
    return {
        MOBILITY: base / cfg.sources.mobility.file,
        MIGRATION: base / cfg.sources.migration.file,
    }


def fingerprint(paths: dict[str, Path]) -> str:
    """One digest over every source, keyed by role so swapping two files changes it."""
    combined = hashlib.sha256()
    for role in sorted(paths):
        combined.update(f"{role}:{paths[role].name}:{file_digest(paths[role])}\n".encode())
    return combined.hexdigest()


def read_sheet(path: Path, sheet: str) -> pd.DataFrame:
    with warnings.catch_warnings():
        # the source workbooks lack a default style and openpyxl warns on every read
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        return pd.read_excel(path, sheet_name=sheet)


def run(cfg: Config, state: PipelineState) -> None:
    paths = source_paths(cfg)
    missing = [str(p) for p in paths.values() if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"source files not found: {', '.join(missing)}")

    state.source_fingerprint = fingerprint(paths)
    state.raw = {
        MOBILITY: read_sheet(paths[MOBILITY], cfg.sources.mobility.sheet),
        MIGRATION: read_sheet(paths[MIGRATION], cfg.sources.migration.sheet),
    }
