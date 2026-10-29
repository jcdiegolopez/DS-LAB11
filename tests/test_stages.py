from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pipeline.checks.common import MONTH_CODE, TRAVELERS, VISITOR_TYPE, YEAR
from pipeline.config import Config, load_config
from pipeline.contracts import PipelineState, RunContext
from pipeline.evaluation import baselines
from pipeline.stages import estimation, fitting, preparation, reading
from pipeline.stages.preparation import PreparedData

ROOT = Path(__file__).resolve().parent.parent
FLORES, REMATE, AIRPORT = "Isla De Flores", "El Remate Y Alrededores Lago", "Mundo Maya Aeropuerto"


@pytest.fixture
def cfg() -> Config:
    return load_config(ROOT / "config.yaml")


@pytest.fixture
def state(tmp_path) -> PipelineState:
    context = RunContext("test-run", datetime.now(timezone.utc), "abc123", tmp_path)
    return PipelineState(context=context)


def make_mobility(cfg: Config) -> pd.DataFrame:
    rows = []
    for month in cfg.coverage.mobility_months:
        year, mon = map(int, month.split("-"))
        for dest, base in ((FLORES, 100.0), (REMATE, 200.0), (AIRPORT, 300.0)):
            for country in ("Alemania", "Guatemala"):
                for segment in ("mayor a 1 dia", "menor a 1 dia"):
                    rows.append({
                        "destino": dest, "sub_grupo": "Peten", "anio": year, "mes": mon,
                        "pais": country, "es_consecutivo": segment,
                        "fecha": pd.Timestamp(year, mon, 1),
                        "visitantes": base, "dias_persona": base, "permanencia_prom": 1.0,
                    })
    return pd.DataFrame(rows)


def make_migration(cfg: Config, per_type: float = 1000.0) -> pd.DataFrame:
    rows = []
    for period in pd.period_range(cfg.coverage.migration_first_period,
                                  cfg.coverage.expected_last_period.migration, freq="M"):
        for kind in ("Turista", "Excursionista", "Viajero"):
            rows.append({YEAR: period.year, MONTH_CODE: period.month, VISITOR_TYPE: kind, TRAVELERS: per_type})
    return pd.DataFrame(rows)


def raw(cfg: Config) -> dict:
    return {"mobility": make_mobility(cfg), "migration": make_migration(cfg)}


def test_reading_loads_both_sheets_and_fingerprints(cfg, state, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    make_mobility(cfg).to_excel(data_dir / cfg.sources.mobility.file, sheet_name=cfg.sources.mobility.sheet, index=False)
    make_migration(cfg).to_excel(data_dir / cfg.sources.migration.file, sheet_name=cfg.sources.migration.sheet, index=False)
    local = cfg.model_copy(update={"paths": cfg.paths.model_copy(update={"data_dir": data_dir})})

    reading.run(local, state)
    first = state.source_fingerprint
    assert set(state.raw) == {"mobility", "migration"}
    assert len(state.raw["mobility"]) == len(make_mobility(cfg))

    reading.run(local, state)
    assert state.source_fingerprint == first and len(first) == 64


def test_reading_fails_clearly_when_a_source_is_missing(cfg, state, tmp_path):
    local = cfg.model_copy(update={"paths": cfg.paths.model_copy(update={"data_dir": tmp_path})})
    with pytest.raises(FileNotFoundError, match="source files not found"):
        reading.run(local, state)


def test_preparation_keeps_foreign_visitors_per_subdestination(cfg):
    data = preparation.prepare(cfg, raw(cfg))
    assert list(data.visitors.columns) == cfg.target.subdestinations
    # two stay segments of the foreign country; Guatemala is excluded
    assert data.visitors.loc["2025-09", FLORES] == 200.0
    assert data.visitors.loc["2025-09", AIRPORT] == 600.0


def test_preparation_leaves_uncovered_months_empty_not_zero(cfg):
    data = preparation.prepare(cfg, raw(cfg))
    for month in cfg.coverage.months_to_estimate:
        assert data.visitors.loc[month].isna().all()
    assert data.observed_months() == cfg.coverage.mobility_months


def test_preparation_adds_only_configured_visitor_types(cfg):
    data = preparation.prepare(cfg, raw(cfg))
    assert data.migration.loc["2026-01"] == 2000.0
    assert data.migration.index[0] == cfg.coverage.migration_first_period
    assert data.migration.index[-1] == cfg.coverage.expected_last_period.migration


def small_data() -> PreparedData:
    months = ["2025-01", "2025-02", "2025-03", "2025-04"]
    visitors = pd.DataFrame({"A": [10.0, 30.0, np.nan, 20.0]}, index=months)
    migration = pd.Series([100.0, 200.0, 150.0, 100.0], index=months)
    return PreparedData(visitors=visitors, migration=migration)


def test_ratio_of_sums_and_mean_of_ratios_differ_as_defined():
    data = small_data()
    months = ["2025-01", "2025-02"]
    assert fitting.fit_factors(data, months, "ratio_of_sums").factors["A"] == pytest.approx(40 / 300)
    assert fitting.fit_factors(data, months, "mean_of_ratios").factors["A"] == pytest.approx((0.1 + 0.15) / 2)


def test_fit_rejects_months_without_mobility():
    with pytest.raises(ValueError, match="without both"):
        fitting.fit_factors(small_data(), ["2025-01", "2025-03"], "ratio_of_sums")


def test_training_skips_months_without_migration(cfg):
    data = preparation.prepare(cfg, raw(cfg))
    months = fitting.training_months(data)
    assert all(m <= cfg.coverage.expected_last_period.migration for m in months)
    assert "2026-07" not in months and "2025-09" in months


def test_estimation_writes_the_contract_with_estimated_months(cfg, state):
    preparation.run(cfg, _with_raw(state, cfg))
    fitting.run(cfg, state)
    estimation.run(cfg, state)

    written = pd.read_csv(state.context.work_dir / estimation.ESTIMATES_FILE)
    assert list(written.columns) == estimation.COLUMNS
    estimated = written[written["kind"] == "estimated"]
    assert sorted(estimated["period"].unique()) == cfg.coverage.months_to_estimate
    assert len(estimated) == 2 * len(cfg.target.subdestinations)
    # factor = 200 / 2000 for Flores; January migration is 2000
    flores = estimated[(estimated["subdestination"] == FLORES) & (estimated["period"] == "2026-01")]
    assert flores["value"].iloc[0] == pytest.approx(200.0)
    assert (written["run_id"] == "test-run").all()


def test_estimate_without_migration_is_empty_not_zero(cfg, state):
    data = small_data()
    model = fitting.fit_factors(data, ["2025-01", "2025-02"], "ratio_of_sums")
    predicted = model.predict(data.migration, ["2025-02", "2026-01"])
    assert predicted.loc["2025-02", "A"] > 0
    assert np.isnan(predicted.loc["2026-01", "A"])


def _with_raw(state: PipelineState, cfg: Config) -> PipelineState:
    state.raw = raw(cfg)
    return state


def test_baselines_use_only_earlier_observed_months():
    visitors = small_data().visitors
    assert baselines.last_observed(visitors["A"], "2025-04") == 30.0
    assert baselines.prior_mean(visitors["A"], "2025-04") == 20.0
    assert np.isnan(baselines.last_observed(visitors["A"], "2025-01"))
    table = baselines.predict("prior_mean", visitors, ["2025-02", "2025-04"])
    assert table["A"].tolist() == [10.0, 20.0]
