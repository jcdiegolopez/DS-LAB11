import json

import numpy as np
import pandas as pd
import pytest

from pipeline.contracts import CheckResult, CheckStatus
from pipeline.monitoring import drill, monitors
from pipeline.monitoring.log import HISTORY_FILE, RUN_LOG_JSON, RUN_LOG_MD, read_history
from pipeline.publish import runner
from pipeline.publish.restore import main as restore_main
from pipeline.publish.store import current_version, list_versions
from pipeline.run import main
from tests.helpers import make_estimates, make_state
from tests.test_stages import make_migration, make_mobility


def raw_for(cfg):
    return {"mobility": make_mobility(cfg), "migration": make_migration(cfg)}


# freshness

def test_freshness_ok_when_sources_reach_the_expected_periods(cfg):
    state = make_state(cfg)
    state.raw = raw_for(cfg)
    result = monitors.freshness(cfg, state, None, None)
    assert result.status == monitors.OK
    assert result.info["latest_period"] == {"mobility": "2026-08", "migration": "2026-06"}


def test_freshness_alerts_when_a_source_is_behind(cfg):
    state = make_state(cfg)
    state.raw = raw_for(cfg)
    state.raw["mobility"] = state.raw["mobility"][state.raw["mobility"]["mes"] != 8]
    result = monitors.freshness(cfg, state, None, None)
    assert result.status == monitors.ALERT
    assert any("mobility: data ends at 2026-07" in a for a in result.alerts)


def test_freshness_alerts_when_newer_data_is_not_configured(cfg):
    state = make_state(cfg)
    state.raw = raw_for(cfg)
    extra = state.raw["migration"].tail(3).assign(**{"Mes cod": 7})
    state.raw["migration"] = pd.concat([state.raw["migration"], extra])
    result = monitors.freshness(cfg, state, None, None)
    assert any("past the configured 2026-06" in a for a in result.alerts)


def test_freshness_alerts_when_the_approved_version_is_stale(cfg):
    state = make_state(cfg)
    state.raw = raw_for(cfg)
    meta = {"run_id": "old", "generated_at": "2026-10-01", "source_fingerprint": "b" * 64}
    result = monitors.freshness(cfg, state, {"source_fingerprint": "b" * 64}, meta)
    assert result.info["sources_changed_since_previous_run"] is True
    assert any("built from different sources" in a for a in result.alerts)


def test_freshness_is_skipped_without_data(cfg):
    assert monitors.freshness(cfg, make_state(cfg), None, None).status == monitors.SKIPPED


# quality

def test_quality_first_run_is_the_baseline(cfg):
    profile = monitors.quality_profile(cfg, raw_for(cfg))
    result = monitors.quality(cfg, profile, None)
    assert result.status == monitors.OK and "baseline" in result.detail


def test_quality_profile_is_none_when_columns_are_missing(cfg):
    raw = raw_for(cfg)
    raw["mobility"] = raw["mobility"].drop(columns="anio")
    assert monitors.quality_profile(cfg, raw) is None
    assert monitors.quality(cfg, None, None).status == monitors.SKIPPED


def test_quality_unchanged_data_raises_no_alert(cfg):
    profile = monitors.quality_profile(cfg, raw_for(cfg))
    assert monitors.quality(cfg, profile, ("prev", profile)).status == monitors.OK


def test_quality_alerts_on_more_nulls_duplicates_and_lost_months(cfg):
    before = monitors.quality_profile(cfg, raw_for(cfg))
    raw = raw_for(cfg)
    mobility = raw["mobility"]
    mobility = mobility[mobility["mes"] != 9].reset_index(drop=True)
    mobility.loc[:20, "pais"] = None
    raw["mobility"] = pd.concat([mobility, mobility.iloc[[30]]], ignore_index=True)

    result = monitors.quality(cfg, monitors.quality_profile(cfg, raw), ("prev", before))

    text = " | ".join(result.alerts)
    assert result.status == monitors.ALERT
    assert "missing 'pais'" in text
    assert "duplicated keys: 0 -> 2" in text
    assert "2025-09" in text


def test_quality_alerts_on_a_large_row_drop(cfg):
    before = monitors.quality_profile(cfg, raw_for(cfg))
    raw = raw_for(cfg)
    raw["migration"] = raw["migration"].iloc[: len(raw["migration"]) // 2]
    result = monitors.quality(cfg, monitors.quality_profile(cfg, raw), ("prev", before))
    assert any(a.startswith("migration_rows") for a in result.alerts)


# results

def test_results_ok_for_smooth_estimates(cfg):
    state = make_state(cfg, estimates=make_estimates(value_jan=5000.0))
    state.estimates.loc[2, "value"] = 4800.0
    assert monitors.results(cfg, state, None).status == monitors.OK


def test_results_alerts_on_negative_and_non_finite_values(cfg):
    estimates = make_estimates(value_jan=-1.0)
    estimates.loc[2, "value"] = np.inf
    result = monitors.results(cfg, make_state(cfg, estimates=estimates), None)
    assert "1 negative values" in result.alerts and "1 non-finite values" in result.alerts


def test_results_alerts_on_a_large_month_to_month_change(cfg):
    result = monitors.results(cfg, make_state(cfg, estimates=make_estimates(value_jan=20000.0)), None)
    assert any("2025-12 -> 2026-01" in a for a in result.alerts)


def test_results_empty_month_is_not_a_change(cfg):
    result = monitors.results(cfg, make_state(cfg, estimates=make_estimates(value_jan=np.nan)), None)
    assert result.status == monitors.OK


def test_results_alerts_on_change_against_the_approved_version(cfg):
    state = make_state(cfg, estimates=make_estimates(value_jan=5000.0))
    approved = make_estimates(value_jan=2000.0)
    result = monitors.results(cfg, state, ("old-run", approved))
    assert any("approved old-run" in a for a in result.alerts)


def test_results_is_skipped_without_estimates(cfg):
    state = make_state(cfg)
    state.estimates = None
    assert monitors.results(cfg, state, None).status == monitors.SKIPPED


# run log written by main

def fake_estimate(c, s):
    s.estimates = make_estimates()
    s.model = {"Isla De Flores": 0.014846}
    s.metrics = {"mae_isla_de_flores": 1606.0}
    s.accepted = True


def last_log(cfg):
    run_id = read_history(cfg)[-1]["run_id"]
    return json.loads((cfg.paths.work_dir / run_id / RUN_LOG_JSON).read_text(encoding="utf-8"))


def test_main_writes_the_run_log_and_history(cfg, config_path):
    stages = [("estimate", fake_estimate), ("publish", "pipeline.publish.runner")]
    assert main(["--config", str(config_path)], stages) == 0

    log = last_log(cfg)
    assert [(s["name"], s["outcome"]) for s in log["stages"]] == [("estimate", "ok"), ("publish", "ok")]
    assert log["status"] == "success"
    assert log["publication"]["published"] is True
    assert log["publication"]["approved_before"] is None
    assert log["publication"]["approved_after"] == log["run_id"]
    assert {m["name"] for m in log["monitors"]} == {"freshness", "quality", "results"}
    assert (cfg.paths.work_dir / log["run_id"] / RUN_LOG_MD).is_file()
    assert (cfg.paths.work_dir / HISTORY_FILE).is_file()


def test_failed_run_log_shows_the_blocked_stage_and_the_untouched_approved_version(cfg, config_path):
    main(["--config", str(config_path)], [("estimate", fake_estimate), ("publish", "pipeline.publish.runner")])
    approved = current_version(cfg.paths.approved_dir)

    def failing(c, s):
        s.check_results.append(CheckResult("uniqueness", CheckStatus.ERROR, "duplicated key"))

    assert main(["--config", str(config_path)], [("validate", failing), ("publish", "pipeline.publish.runner")]) == 1

    log = last_log(cfg)
    assert log["stages"] == [dict(log["stages"][0], name="validate", outcome="blocked")]
    assert log["checks"]["blocking"] == ["uniqueness"]
    assert log["publication"]["approved_unchanged"] is True
    assert log["publication"]["approved_after"] == approved
    assert "critical quality check" in log["publication"]["reason"]


def test_a_stage_error_is_logged_with_its_message(cfg, config_path):
    def boom(c, s):
        raise ValueError("bad sheet")

    assert main(["--config", str(config_path)], [("read", boom)]) == 1
    stage = last_log(cfg)["stages"][0]
    assert stage["outcome"] == "failed" and stage["error"] == "bad sheet"


def test_result_alerts_reach_the_console_without_changing_the_exit_code(cfg, config_path, capsys):
    def jumpy(c, s):
        fake_estimate(c, s)
        s.estimates = make_estimates(value_jan=20000.0)

    assert main(["--config", str(config_path)], [("estimate", jumpy), ("publish", "pipeline.publish.runner")]) == 0
    assert "alert: results:" in capsys.readouterr().err
    assert last_log(cfg)["alerts"]


def test_restore_is_recorded_in_the_history(cfg, config_path):
    runner.run(cfg, make_state(cfg, run_id="run-1"))
    runner.run(cfg, make_state(cfg, run_id="run-2"))

    assert restore_main(["--config", str(config_path), "--to", "run-1"]) == 0

    event = read_history(cfg)[-1]
    assert event["event"] == "restore" and event["from"] == "run-2" and event["to"] == "run-1"


def test_a_corrupt_history_line_is_skipped(cfg, config_path):
    cfg.paths.work_dir.mkdir(parents=True, exist_ok=True)
    (cfg.paths.work_dir / HISTORY_FILE).write_text('{"event": "run", "run_id": "a"}\n{"event": "ru\n', encoding="utf-8")
    assert [e["run_id"] for e in read_history(cfg)] == ["a"]


# controlled failure drill, end to end on synthetic workbooks

def accept(c, s):
    s.metrics = {"mae_isla_de_flores": 1.0}
    s.accepted = True


def drill_stages():
    return [
        ("read", "pipeline.stages.reading"),
        ("validate", "pipeline.checks.runner"),
        ("prepare", "pipeline.stages.preparation"),
        ("fit", "pipeline.stages.fitting"),
        ("evaluate", accept),
        ("estimate", "pipeline.stages.estimation"),
        ("publish", "pipeline.publish.runner"),
    ]


@pytest.fixture
def workbooks(cfg):
    cfg.paths.data_dir.mkdir(parents=True, exist_ok=True)
    make_mobility(cfg).to_excel(cfg.paths.data_dir / cfg.sources.mobility.file, sheet_name=cfg.sources.mobility.sheet, index=False)
    make_migration(cfg).to_excel(cfg.paths.data_dir / cfg.sources.migration.file, sheet_name=cfg.sources.migration.sheet, index=False)


@pytest.mark.parametrize("mode", sorted(drill.MODES))
def test_drill_detects_preserves_and_recovers(cfg, config_path, workbooks, tmp_path, mode):
    run = lambda argv: main(argv, drill_stages())  # noqa: E731
    assert run(["--config", str(config_path)]) == 0
    approved = current_version(cfg.paths.approved_dir)
    original = (cfg.paths.data_dir / cfg.sources.mobility.file).read_bytes()

    report = drill.run_drill(config_path, mode, run_pipeline=run, evidence_dir=tmp_path / "evidence")

    assert report["detected"], report
    assert report["damaged_run"]["exit_code"] == 1
    assert report["approved_preserved"]
    assert report["approved"]["before"] == approved
    assert report["recovered_validation"]
    assert report["fixed_run"]["exit_code"] == 0 and report["fixed_run"]["published"]
    assert len(list_versions(cfg.paths.approved_dir)) == 2
    assert (cfg.paths.data_dir / cfg.sources.mobility.file).read_bytes() == original
    assert "Failure detected | yes" in (tmp_path / "evidence").joinpath(report["evidence_file"].split("/")[-1]).read_text()
