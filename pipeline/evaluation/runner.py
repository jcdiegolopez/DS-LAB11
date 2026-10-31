"""Growing-window temporal validation and the acceptance rule.

For each evaluated month the factor is fitted only on observed months before it, and the
prediction is compared with the observed value next to the simple references, which see the
same months. The months to estimate have no observation, so they never enter an error.
"""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

from pipeline.config import Config
from pipeline.contracts import PipelineState
from pipeline.evaluation import baselines
from pipeline.serialization import to_json
from pipeline.stages.fitting import fit_factors, training_months
from pipeline.stages.preparation import PreparedData

EVALUATION_CSV = "evaluation.csv"
EVALUATION_JSON = "evaluation.json"
MODEL = "factor"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def backtest(cfg: Config, data: PreparedData) -> pd.DataFrame:
    """One row per evaluated month and subdestination with the observed value and every prediction."""
    available = training_months(data)
    rows = []
    for month in cfg.evaluation.eval_months:
        if month not in available:
            raise ValueError(f"eval month {month} lacks mobility or migration data")
        train = [m for m in available if m < month]
        if len(train) < cfg.evaluation.min_train_months:
            raise ValueError(
                f"eval month {month} has {len(train)} training months, "
                f"fewer than min_train_months={cfg.evaluation.min_train_months}"
            )
        model = fit_factors(data, train, cfg.model_params.factor_method)
        predicted = {MODEL: model.predict(data.migration, [month]).loc[month]}
        # the references only look at the training months, like the factor
        history = data.visitors.loc[train]
        for name in cfg.evaluation.baselines:
            predicted[name] = baselines.predict(name, history, [month]).loc[month]

        for sub in cfg.target.subdestinations:
            row = {"period": month, "subdestination": sub, "train_months": len(train),
                   "observed": data.visitors.loc[month, sub]}
            row.update({name: values[sub] for name, values in predicted.items()})
            rows.append(row)
    return pd.DataFrame(rows)


def _mae(errors: pd.Series) -> float:
    return float(errors.abs().mean())


def _rmse(errors: pd.Series) -> float:
    return float(np.sqrt((errors ** 2).mean()))


def compute_metrics(cfg: Config, table: pd.DataFrame) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for name in [MODEL, *cfg.evaluation.baselines]:
        prefix = "" if name == MODEL else f"{name}_"
        errors = table[name] - table["observed"]
        metrics[f"{prefix}mae"] = _mae(errors)
        metrics[f"{prefix}rmse"] = _rmse(errors)
        for sub, group in table.assign(error=errors).groupby("subdestination"):
            metrics[f"{prefix}mae_{slug(sub)}"] = _mae(group["error"])
            metrics[f"{prefix}rmse_{slug(sub)}"] = _rmse(group["error"])

    best = min(metrics[f"{name}_mae"] for name in cfg.evaluation.baselines)
    metrics["best_baseline_mae"] = best
    if best > 0:
        metrics["mae_ratio_vs_best_baseline"] = metrics["mae"] / best
    metrics["mae_relative_to_level"] = metrics["mae"] / float(table["observed"].mean())
    metrics["eval_month_count"] = float(table["period"].nunique())
    return metrics


def decide(cfg: Config, table: pd.DataFrame, metrics: dict[str, float]) -> tuple[bool, list[dict]]:
    """Apply the acceptance rule; every condition is reported, passed or not."""
    limits = cfg.thresholds
    predictions = table[MODEL].to_numpy(dtype=float)
    rules = [{
        "rule": "predictions for every evaluated month are finite and non-negative",
        "passed": bool(np.isfinite(predictions).all() and (predictions >= 0).all()),
        "value": int(np.isfinite(predictions).sum()),
        "limit": len(predictions),
    }]
    if limits.max_mae_ratio_vs_baseline is not None:
        ratio = metrics.get("mae_ratio_vs_best_baseline", math.inf)
        rules.append({
            "rule": "MAE of the factor relative to the best simple reference",
            "passed": ratio <= limits.max_mae_ratio_vs_baseline,
            "value": ratio,
            "limit": limits.max_mae_ratio_vs_baseline,
        })
    if limits.max_mae is not None:
        rules.append({
            "rule": "overall MAE of the factor in visitors",
            "passed": metrics["mae"] <= limits.max_mae,
            "value": metrics["mae"],
            "limit": limits.max_mae,
        })
    if len(rules) == 1:
        rules.append({"rule": "an error threshold is configured", "passed": False, "value": None, "limit": None})
    return all(r["passed"] for r in rules), rules


def run(cfg: Config, state: PipelineState) -> None:
    table = backtest(cfg, state.prepared)
    metrics = compute_metrics(cfg, table)
    accepted, rules = decide(cfg, table, metrics)

    work_dir = state.context.work_dir
    table.to_csv(work_dir / EVALUATION_CSV, index=False)
    summary = {"accepted": accepted, "rules": rules, "metrics": metrics,
               "factor_method": cfg.model_params.factor_method,
               "min_train_months": cfg.evaluation.min_train_months}
    (work_dir / EVALUATION_JSON).write_text(to_json(summary), encoding="utf-8")

    state.metrics.update({k: v for k, v in metrics.items() if math.isfinite(v)})
    state.accepted = accepted
    if not accepted:
        failed = "; ".join(r["rule"] for r in rules if not r["passed"])
        state.warnings.append(f"acceptance rule not met: {failed}")
