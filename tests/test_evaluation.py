import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from pipeline.checks.common import month_range
from pipeline.contracts import PipelineState, RunContext
from pipeline.evaluation import runner
from pipeline.stages.preparation import PreparedData

SHARES = {"Isla De Flores": 0.02, "El Remate Y Alrededores Lago": 0.03, "Mundo Maya Aeropuerto": 0.05}


def make_data(cfg, shares=SHARES, noise=None) -> PreparedData:
    first = cfg.coverage.mobility_months[0]
    last = cfg.coverage.mobility_months[-1]
    months = month_range(first, last)
    migration_months = month_range(cfg.coverage.migration_first_period, cfg.coverage.expected_last_period.migration)
    migration = pd.Series(
        [100_000.0 + 20_000.0 * (i % 5) for i in range(len(migration_months))], index=migration_months
    )
    visitors = pd.DataFrame(index=months, columns=list(shares), dtype=float)
    for month in cfg.coverage.mobility_months:
        if month in migration.index:
            for sub, share in shares.items():
                visitors.loc[month, sub] = migration[month] * share * (noise or {}).get(month, 1.0)
        else:
            visitors.loc[month] = 1000.0
    return PreparedData(visitors=visitors, migration=migration)


def make_state(tmp_path, data) -> PipelineState:
    state = PipelineState(context=RunContext("eval-run", datetime.now(timezone.utc), "abc", tmp_path))
    state.prepared = data
    return state


def test_each_month_is_fitted_only_on_earlier_months(cfg):
    table = runner.backtest(cfg, make_data(cfg))
    observed = [m for m in cfg.coverage.mobility_months if m <= cfg.coverage.expected_last_period.migration]
    for month, group in table.groupby("period"):
        assert (group["train_months"] == sum(m < month for m in observed)).all()
    assert sorted(table["period"].unique()) == cfg.evaluation.eval_months


def test_a_later_month_never_changes_an_earlier_prediction(cfg):
    base = runner.backtest(cfg, make_data(cfg))
    changed = runner.backtest(cfg, make_data(cfg, noise={"2026-06": 3.0}))
    before = base["period"] < "2026-06"
    pd.testing.assert_frame_equal(base[before], changed[before])


def test_months_to_estimate_never_enter_the_errors(cfg):
    table = runner.backtest(cfg, make_data(cfg))
    assert not set(table["period"]) & set(cfg.coverage.months_to_estimate)


def test_stable_share_is_exact_and_accepted(cfg):
    table = runner.backtest(cfg, make_data(cfg))
    metrics = runner.compute_metrics(cfg, table)
    accepted, rules = runner.decide(cfg, table, metrics)
    assert metrics["mae"] == pytest.approx(0.0, abs=1e-6)
    assert metrics["last_observed_mae"] > 0
    assert accepted and all(r["passed"] for r in rules)


def test_losing_to_the_reference_is_rejected(cfg):
    noise = {m: (2.0 if i % 2 else 0.5) for i, m in enumerate(cfg.coverage.mobility_months)}
    table = runner.backtest(cfg, make_data(cfg, noise=noise))
    metrics = runner.compute_metrics(cfg, table)
    accepted, rules = runner.decide(cfg, table, metrics)
    assert not accepted
    assert any(not r["passed"] for r in rules)


def test_without_error_thresholds_nothing_is_accepted(cfg):
    open_cfg = cfg.model_copy(update={"thresholds": cfg.thresholds.model_copy(
        update={"max_mae": None, "max_mae_ratio_vs_baseline": None})})
    table = runner.backtest(open_cfg, make_data(cfg))
    accepted, rules = runner.decide(open_cfg, table, runner.compute_metrics(open_cfg, table))
    assert not accepted and rules[-1]["rule"] == "an error threshold is configured"


def test_too_few_training_months_fails_clearly(cfg):
    strict = cfg.model_copy(update={"evaluation": cfg.evaluation.model_copy(update={"min_train_months": 4})})
    with pytest.raises(ValueError, match="fewer than min_train_months"):
        runner.backtest(strict, make_data(cfg))


def test_run_sets_metrics_decision_and_writes_files(cfg, tmp_path):
    state = make_state(tmp_path, make_data(cfg))
    runner.run(cfg, state)
    assert state.accepted is True
    assert all(np.isfinite(v) for v in state.metrics.values())
    assert {"mae", "rmse", "mae_isla_de_flores", "last_observed_mae", "prior_mean_mae"} <= set(state.metrics)

    summary = json.loads((tmp_path / runner.EVALUATION_JSON).read_text(encoding="utf-8"))
    assert summary["accepted"] is True
    written = pd.read_csv(tmp_path / runner.EVALUATION_CSV)
    assert len(written) == len(cfg.evaluation.eval_months) * len(SHARES)


def test_rejection_is_explained_in_the_warnings(cfg, tmp_path):
    noise = {m: (2.0 if i % 2 else 0.5) for i, m in enumerate(cfg.coverage.mobility_months)}
    state = make_state(tmp_path, make_data(cfg, noise=noise))
    runner.run(cfg, state)
    assert state.accepted is False
    assert any(w.startswith("acceptance rule not met") for w in state.warnings)
