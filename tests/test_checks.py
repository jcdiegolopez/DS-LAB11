import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pipeline.checks import (
    columns_types, dates_coverage, methodology, missing_values, uniqueness, values_denominators,
)
from pipeline.checks.common import MONTH_CODE, TRAVELERS, VISITOR_TYPE, YEAR
from pipeline.checks.runner import REPORT_JSON, REPORT_MD, run, run_checks
from pipeline.config import Config, load_config
from pipeline.contracts import CheckStatus, PipelineState, RunContext

ROOT = Path(__file__).resolve().parent.parent
SUBS = ["Isla De Flores", "El Remate Y Alrededores Lago", "Mundo Maya Aeropuerto"]


@pytest.fixture
def cfg() -> Config:
    return load_config(ROOT / "config.yaml")


def make_mobility(cfg: Config) -> pd.DataFrame:
    rows = []
    for month in cfg.coverage.mobility_months:
        year, mon = map(int, month.split("-"))
        for dest in SUBS:
            for country in ("Alemania", "Guatemala"):
                for segment, days in (("mayor a 1 dia", 3.0), ("menor a 1 dia", 1.0)):
                    rows.append({
                        "destino": dest, "sub_grupo": "Peten", "anio": year, "mes": mon,
                        "pais": country, "es_consecutivo": segment,
                        "fecha": pd.Timestamp(year, mon, 1),
                        "visitantes": 10.0, "dias_persona": 10.0 * days, "permanencia_prom": days,
                    })
    return pd.DataFrame(rows)


def make_migration(cfg: Config) -> pd.DataFrame:
    periods = pd.period_range(cfg.coverage.migration_first_period, cfg.coverage.expected_last_period.migration, freq="M")
    rows = []
    for p in periods:
        for kind in ("Turista", "Excursionista", "Cruceristas"):
            rows.append({YEAR: p.year, MONTH_CODE: p.month, VISITOR_TYPE: kind, TRAVELERS: 100.0})
    return pd.DataFrame(rows)


@pytest.fixture
def raw(cfg):
    return {"mobility": make_mobility(cfg), "migration": make_migration(cfg)}


def status(module, cfg, raw) -> CheckStatus:
    return module.check(cfg, raw).status


# a) columns and types

def test_columns_ok(cfg, raw):
    assert status(columns_types, cfg, raw) is CheckStatus.OK


def test_missing_required_column_stops(cfg, raw):
    raw["mobility"] = raw["mobility"].drop(columns="visitantes")
    result = columns_types.check(cfg, raw)
    assert result.status is CheckStatus.ERROR and result.blocks_pipeline
    assert "visitantes" in result.detail


def test_missing_migration_column_stops(cfg, raw):
    raw["migration"] = raw["migration"].drop(columns=TRAVELERS)
    assert status(columns_types, cfg, raw) is CheckStatus.ERROR


def test_incompatible_type_stops(cfg, raw):
    raw["mobility"]["visitantes"] = "ten"
    assert status(columns_types, cfg, raw) is CheckStatus.ERROR


def test_missing_optional_column_warns(cfg, raw):
    raw["mobility"] = raw["mobility"].drop(columns="permanencia_prom")
    assert status(columns_types, cfg, raw) is CheckStatus.WARNING


# b) dates and coverage

def test_uncovered_months_to_estimate_only_warn(cfg, raw):
    result = dates_coverage.check(cfg, raw)
    assert result.status is CheckStatus.WARNING
    assert "2026-01" in result.detail and "2026-02" in result.detail


def test_date_disagreeing_with_year_month_stops(cfg, raw):
    raw["mobility"].loc[0, "mes"] = 11
    assert status(dates_coverage, cfg, raw) is CheckStatus.ERROR


def test_invalid_date_stops(cfg, raw):
    raw["mobility"]["fecha"] = raw["mobility"]["fecha"].astype(object)
    raw["mobility"].loc[0, "fecha"] = "not a date"
    assert status(dates_coverage, cfg, raw) is CheckStatus.ERROR


def test_missing_expected_mobility_month_stops(cfg, raw):
    mob = raw["mobility"]
    raw["mobility"] = mob[~((mob["anio"] == 2026) & (mob["mes"] == 4))]
    result = dates_coverage.check(cfg, raw)
    assert result.status is CheckStatus.ERROR and "2026-04" in result.detail


def test_missing_migration_month_stops(cfg, raw):
    mig = raw["migration"]
    raw["migration"] = mig[~((mig[YEAR] == 2015) & (mig[MONTH_CODE] == 7))]
    result = dates_coverage.check(cfg, raw)
    assert result.status is CheckStatus.ERROR and "2015-07" in result.detail


# c) uniqueness

def test_unique_key_ok(cfg, raw):
    assert status(uniqueness, cfg, raw) is CheckStatus.OK


def test_duplicated_key_stops(cfg, raw):
    mob = raw["mobility"]
    raw["mobility"] = pd.concat([mob, mob.iloc[[0]]], ignore_index=True)
    result = uniqueness.check(cfg, raw)
    assert result.status is CheckStatus.ERROR and "2 rows share a key" in result.detail


# d) missing values

def test_no_missing_ok(cfg, raw):
    assert status(missing_values, cfg, raw) is CheckStatus.OK


def test_few_null_countries_warn(cfg, raw):
    raw["mobility"].loc[0, "pais"] = None
    assert status(missing_values, cfg, raw) is CheckStatus.WARNING


def test_null_countries_above_threshold_stop(cfg, raw):
    mob = raw["mobility"]
    mob.loc[mob.index[: len(mob) // 10], "pais"] = None
    assert status(missing_values, cfg, raw) is CheckStatus.ERROR


def test_null_visitors_stop(cfg, raw):
    raw["mobility"].loc[0, "visitantes"] = np.nan
    assert status(missing_values, cfg, raw) is CheckStatus.ERROR


def test_missing_migration_for_month_to_estimate_stops(cfg, raw):
    mig = raw["migration"]
    raw["migration"] = mig[~((mig[YEAR] == 2026) & (mig[MONTH_CODE] == 1))]
    result = missing_values.check(cfg, raw)
    assert result.status is CheckStatus.ERROR and "2026-01" in result.detail


def test_null_migration_in_used_month_stops(cfg, raw):
    mig = raw["migration"]
    mig.loc[(mig[YEAR] == 2025) & (mig[MONTH_CODE] == 10) & (mig[VISITOR_TYPE] == "Turista"), TRAVELERS] = np.nan
    assert status(missing_values, cfg, raw) is CheckStatus.ERROR


# e) values and denominators

def test_values_ok(cfg, raw):
    assert status(values_denominators, cfg, raw) is CheckStatus.OK


def test_zero_visitors_warn(cfg, raw):
    raw["mobility"].loc[0, "visitantes"] = 0.0
    assert status(values_denominators, cfg, raw) is CheckStatus.WARNING


def test_negative_visitors_stop(cfg, raw):
    raw["mobility"].loc[0, "visitantes"] = -5.0
    assert status(values_denominators, cfg, raw) is CheckStatus.ERROR


def test_infinite_visitors_stop(cfg, raw):
    raw["mobility"].loc[0, "visitantes"] = np.inf
    assert status(values_denominators, cfg, raw) is CheckStatus.ERROR


def test_zero_migration_denominator_stops(cfg, raw):
    mig = raw["migration"]
    month = (mig[YEAR] == 2026) & (mig[MONTH_CODE] == 2)
    mig.loc[month & mig[VISITOR_TYPE].isin(["Turista", "Excursionista"]), TRAVELERS] = 0.0
    result = values_denominators.check(cfg, raw)
    assert result.status is CheckStatus.ERROR and "2026-02" in result.detail


def test_zero_migration_in_unused_month_is_ignored(cfg, raw):
    mig = raw["migration"]
    mig.loc[(mig[YEAR] == 2010) & (mig[MONTH_CODE] == 3), TRAVELERS] = 0.0
    assert status(values_denominators, cfg, raw) is CheckStatus.OK


def test_other_visitor_types_do_not_count_as_denominator(cfg, raw):
    mig = raw["migration"]
    month = (mig[YEAR] == 2026) & (mig[MONTH_CODE] == 3)
    mig.loc[month & (mig[VISITOR_TYPE] != "Cruceristas"), TRAVELERS] = 0.0
    assert status(values_denominators, cfg, raw) is CheckStatus.ERROR


# f) methodology

def test_methodology_ok(cfg, raw):
    assert status(methodology, cfg, raw) is CheckStatus.OK


def test_daily_source_stops(cfg, raw):
    daily = cfg.model_copy(update={"sources": cfg.sources.model_copy(update={
        "mobility": cfg.sources.mobility.model_copy(update={"file": "BD_moviidad_diario.xlsx"})})})
    assert status(methodology, daily, raw) is CheckStatus.ERROR


def test_daily_rows_stop(cfg, raw):
    raw["mobility"].loc[0, "fecha"] = pd.Timestamp(2025, 9, 15)
    assert status(methodology, cfg, raw) is CheckStatus.ERROR


def test_total_row_stops(cfg, raw):
    total = raw["mobility"].iloc[[0]].assign(destino="Total Peten")
    raw["mobility"] = pd.concat([raw["mobility"], total], ignore_index=True)
    result = methodology.check(cfg, raw)
    assert result.status is CheckStatus.ERROR and "Total Peten" in result.detail


def test_stay_not_derivable_stops(cfg, raw):
    raw["mobility"].loc[0, "permanencia_prom"] = 9.0
    assert status(methodology, cfg, raw) is CheckStatus.ERROR


# runner and report

def test_runner_returns_one_result_per_check(cfg, raw):
    results = run_checks(cfg, raw)
    assert [r.name for r in results] == [
        "columns_types", "dates_coverage", "uniqueness", "missing_values", "values_denominators", "methodology",
    ]
    assert not any(r.blocks_pipeline for r in results)


def test_runner_skips_checks_when_columns_fail(cfg, raw):
    raw["mobility"] = raw["mobility"].drop(columns="fecha")
    results = run_checks(cfg, raw)
    assert all(r.status is CheckStatus.ERROR for r in results)
    assert "not run" in results[1].detail


def test_runner_turns_a_crash_into_an_error(cfg):
    results = run_checks(cfg, None)
    assert results[0].status is CheckStatus.ERROR and "crashed" in results[0].detail


def test_run_writes_reports_and_records_warnings(cfg, raw, tmp_path):
    ctx = RunContext("test-run", datetime.now(timezone.utc), "abc", tmp_path)
    state = PipelineState(context=ctx, raw=raw)
    run(cfg, state)

    report = json.loads((tmp_path / REPORT_JSON).read_text(encoding="utf-8"))
    assert report["outcome"] == "passed"
    assert {c["name"] for c in report["checks"]} == {r.name for r in state.check_results}
    assert all(c["verifies"] and c["stops_when"] for c in report["checks"])
    assert any(w.startswith("dates_coverage") for w in state.warnings)
    assert "| dates_coverage | warning | no |" in (tmp_path / REPORT_MD).read_text(encoding="utf-8")


def test_run_with_duplicated_key_reports_blocked(cfg, raw, tmp_path):
    mob = raw["mobility"]
    raw["mobility"] = pd.concat([mob, mob.iloc[[0]]], ignore_index=True)
    state = PipelineState(context=RunContext("bad", datetime.now(timezone.utc), "abc", tmp_path), raw=raw)
    run(cfg, state)
    assert any(r.blocks_pipeline for r in state.check_results)
    assert json.loads((tmp_path / REPORT_JSON).read_text(encoding="utf-8"))["outcome"] == "blocked"
