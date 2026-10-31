import json

import pandas as pd
import pytest

from pipeline.contracts import CheckResult, CheckStatus, RunStatus
from pipeline.publish import runner
from pipeline.run import execute, main
from pipeline.stages.fitting import FactorModel
from pipeline.tracking.compare import compare_runs
from pipeline.tracking.compare import main as compare_main
from pipeline.tracking.recorder import ensure_experiment, get_client, record_run
from tests.helpers import make_estimates, make_state


def fetch(cfg, mlflow_run_id):
    return get_client(cfg).get_run(mlflow_run_id)


def published_state(cfg, run_id, value_jan=4464.0):
    state = make_state(cfg, run_id=run_id, estimates=make_estimates(value_jan=value_jan))
    runner.run(cfg, state)
    return state


def test_published_run_records_data_code_parameters_metrics_and_files(cfg):
    state = published_state(cfg, "run-ok")
    state.check_results.append(CheckResult("uniqueness", CheckStatus.OK, "no duplicates"))
    state.check_results.append(CheckResult("dates_coverage", CheckStatus.WARNING, "jan-feb missing", critical=False))
    (state.context.work_dir / "quality_report.json").write_text("{}", encoding="utf-8")

    run = fetch(cfg, record_run(cfg, state))

    assert run.info.status == "FINISHED"
    assert run.data.tags["outcome"] == "published"
    assert run.data.tags["git_commit"] == "abc1234"
    assert run.data.params["source_fingerprint"] == "a" * 64
    assert run.data.params["factor_method"] == "ratio_of_sums"
    assert run.data.metrics["mae_isla_de_flores"] == 1606.0
    assert run.data.metrics["checks_ok"] == 1.0
    assert run.data.metrics["checks_warning"] == 1.0

    names = {a.path for a in get_client(cfg).list_artifacts(run.info.run_id)}
    assert {"config.json", "estimates.csv", "model_params.json", "quality_report.json", "meta.json"} <= names


def test_a_factor_model_object_is_saved_as_plain_parameters(cfg):
    state = make_state(cfg, run_id="run-model")
    state.model = FactorModel(
        method="ratio_of_sums",
        train_months=("2025-09", "2025-10"),
        factors=pd.Series({"Isla De Flores": 0.0149, "El Remate Y Alrededores Lago": 0.0166}, name="factor"),
    )
    runner.run(cfg, state)

    record_run(cfg, state)

    saved = json.loads((state.context.work_dir / "model_params.json").read_text(encoding="utf-8"))
    assert saved["method"] == "ratio_of_sums"
    assert saved["train_months"] == ["2025-09", "2025-10"]
    assert saved["factors"]["Isla De Flores"] == 0.0149
    meta = json.loads((state.published_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["model"]["factors"]["El Remate Y Alrededores Lago"] == 0.0166


def test_failed_run_is_recorded_with_its_cause_and_without_invented_metrics(cfg):
    state = make_state(cfg, run_id="run-failed", estimates=None)
    state.estimates, state.metrics, state.model, state.accepted = None, {}, None, None
    state.status = RunStatus.FAILED_CHECKS
    state.check_results.append(CheckResult("columns_types", CheckStatus.ERROR, "missing column pais"))

    run = fetch(cfg, record_run(cfg, state))

    assert run.info.status == "FAILED"
    assert run.data.tags["outcome"] == "failed_checks"
    assert "columns_types" in run.data.tags["failure_cause"]
    assert "mae_isla_de_flores" not in run.data.metrics
    assert set(run.data.metrics) == {"checks_ok", "checks_warning", "checks_error"}


def test_stage_failure_is_recorded_with_the_exception(cfg):
    def boom(c, s):
        raise ValueError("bad sheet")

    state = execute(cfg, [("read", boom)])
    run = fetch(cfg, record_run(cfg, state))

    assert run.info.status == "FAILED"
    assert run.data.tags["failure_cause"] == "read: bad sheet"
    assert run.data.metrics == {}


def test_rejected_run_finishes_but_is_marked_rejected(cfg):
    state = make_state(cfg, run_id="run-rej", accepted=False)
    runner.run(cfg, state)

    run = fetch(cfg, record_run(cfg, state))

    assert run.info.status == "FINISHED"
    assert run.data.tags["outcome"] == "rejected"
    assert run.data.tags["published"] == "false"


def test_experiment_is_created_once(cfg):
    client = get_client(cfg)
    assert ensure_experiment(client, cfg) == ensure_experiment(client, cfg)


def test_two_identical_runs_are_equivalent(cfg):
    for run_id in ("run-a", "run-b"):
        record_run(cfg, published_state(cfg, run_id))

    assert compare_runs(cfg, "run-a", "run-b").equivalent


def test_runs_with_different_estimates_are_not_equivalent(cfg):
    record_run(cfg, published_state(cfg, "run-a"))
    record_run(cfg, published_state(cfg, "run-b", value_jan=4500.0))

    result = compare_runs(cfg, "run-a", "run-b")

    assert not result.equivalent
    assert any("estimate values differ" in line for line in result.differences)
    assert compare_runs(cfg, "run-a", "run-b", rtol=0.1).equivalent


def test_compare_rejects_unknown_and_malformed_run_ids(cfg):
    record_run(cfg, published_state(cfg, "run-a"))
    with pytest.raises(ValueError, match="not recorded"):
        compare_runs(cfg, "run-a", "missing")
    with pytest.raises(ValueError, match="invalid run id"):
        compare_runs(cfg, "run-a", "x' OR 1=1 --")


def test_compare_cli_exit_codes(cfg, config_path):
    record_run(cfg, published_state(cfg, "run-a"))
    record_run(cfg, published_state(cfg, "run-b"))
    record_run(cfg, published_state(cfg, "run-c", value_jan=1.0))

    assert compare_main(["--config", str(config_path), "run-a", "run-b"]) == 0
    assert compare_main(["--config", str(config_path), "run-a", "run-c"]) == 1
    assert compare_main(["--config", str(config_path), "run-a", "nope"]) == 1


def fake_estimate(c, s):
    s.estimates = make_estimates()
    s.model = {"Isla De Flores": 0.014846}
    s.metrics = {"mae_isla_de_flores": 1606.0}
    s.accepted = True


def test_main_runs_publish_and_records_end_to_end(cfg, config_path, capsys):
    stages = [("estimate", fake_estimate), ("publish", "pipeline.publish.runner")]

    assert main(["--config", str(config_path)], stages) == 0

    out = capsys.readouterr().out
    assert "status=success" in out and "published:" in out
    run_id = next(line for line in out.splitlines() if line.startswith("run_id=")).split()[0].split("=")[1]
    assert (cfg.paths.approved_dir / run_id / "estimates.csv").is_file()
    assert fetch_by_name(cfg, run_id).data.tags["outcome"] == "published"


def test_main_returns_2_for_a_rejected_version(cfg, config_path):
    def reject(c, s):
        fake_estimate(c, s)
        s.accepted = False

    stages = [("estimate", reject), ("publish", "pipeline.publish.runner")]

    assert main(["--config", str(config_path)], stages) == 2
    assert not (cfg.paths.approved_dir / "current").exists()


def test_main_returns_1_when_a_critical_check_fails(cfg, config_path):
    def failing(c, s):
        s.check_results.append(CheckResult("columns_types", CheckStatus.ERROR, "missing"))

    stages = [("validate", failing), ("publish", "pipeline.publish.runner")]

    assert main(["--config", str(config_path)], stages) == 1
    assert not cfg.paths.approved_dir.exists()


def fetch_by_name(cfg, run_name):
    client = get_client(cfg)
    experiment_id = ensure_experiment(client, cfg)
    return client.search_runs([experiment_id], filter_string=f"tags.mlflow.runName = '{run_name}'")[0]
