from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from pipeline.config import Config, load_config
from pipeline.publish.store import KEY_COLUMNS
from pipeline.tracking.recorder import ensure_experiment, get_client

RUN_ID_PATTERN = re.compile(r"^[\w-]+$")


@dataclass
class Comparison:
    differences: list[str] = field(default_factory=list)

    @property
    def equivalent(self) -> bool:
        return not self.differences


def _find_run(cfg: Config, run_id: str):
    if not RUN_ID_PATTERN.match(run_id):
        raise ValueError(f"invalid run id: {run_id!r}")
    client = get_client(cfg)
    experiment_id = ensure_experiment(client, cfg)
    found = client.search_runs([experiment_id], filter_string=f"tags.mlflow.runName = '{run_id}'", max_results=1)
    if not found:
        raise ValueError(f"run {run_id} is not recorded in MLflow")
    return found[0]


def _compare_estimates(cfg: Config, run_a: str, run_b: str, rtol: float, atol: float) -> list[str]:
    paths = [cfg.paths.work_dir / run / "estimates.csv" for run in (run_a, run_b)]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        return [f"estimates file not found: {', '.join(missing)}"]

    keys = KEY_COLUMNS + ["kind"]
    a, b = (pd.read_csv(p) for p in paths)
    merged = a.merge(b, on=keys, how="outer", suffixes=("_a", "_b"), indicator=True)
    differences = []
    unmatched = int((merged["_merge"] != "both").sum())
    if unmatched:
        differences.append(f"{unmatched} estimate rows exist in only one run")
    both = merged[merged["_merge"] == "both"]
    close = np.isclose(both["value_a"], both["value_b"], rtol=rtol, atol=atol, equal_nan=True)
    if not close.all():
        worst = float((both["value_a"] - both["value_b"]).abs()[~close].max())
        differences.append(f"{int((~close).sum())} estimate values differ beyond tolerance (max abs diff {worst:g})")
    return differences


def compare_runs(cfg: Config, run_a: str, run_b: str, rtol: float = 1e-9, atol: float = 1e-9) -> Comparison:
    first, second = _find_run(cfg, run_a), _find_run(cfg, run_b)
    result = Comparison()

    for key in sorted(set(first.data.params) | set(second.data.params)):
        va, vb = first.data.params.get(key), second.data.params.get(key)
        if va != vb:
            result.differences.append(f"param {key}: {va!r} vs {vb!r}")

    for key in sorted(set(first.data.metrics) | set(second.data.metrics)):
        va, vb = first.data.metrics.get(key), second.data.metrics.get(key)
        if va is None or vb is None or not math.isclose(va, vb, rel_tol=rtol, abs_tol=atol):
            result.differences.append(f"metric {key}: {va} vs {vb}")

    commit_a, commit_b = first.data.tags.get("git_commit"), second.data.tags.get("git_commit")
    if commit_a != commit_b:
        result.differences.append(f"git_commit: {commit_a} vs {commit_b}")

    result.differences += _compare_estimates(cfg, run_a, run_b, rtol, atol)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.tracking.compare")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--rtol", type=float, default=1e-9)
    parser.add_argument("--atol", type=float, default=1e-9)
    parser.add_argument("run_a")
    parser.add_argument("run_b")
    args = parser.parse_args(argv)

    try:
        result = compare_runs(load_config(args.config), args.run_a, args.run_b, args.rtol, args.atol)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if result.equivalent:
        print(f"runs are equivalent (rtol={args.rtol:g}, atol={args.atol:g})")
        return 0
    print("runs differ:")
    for line in result.differences:
        print(f"  - {line}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
