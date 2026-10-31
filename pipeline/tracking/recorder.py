from __future__ import annotations

import math
import os
import re
from pathlib import Path

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

from mlflow import MlflowClient

from pipeline.config import Config
from pipeline.contracts import CheckStatus, PipelineState, RunStatus
from pipeline.publish.store import META_FILE
from pipeline.serialization import to_json, to_plain

MAX_TEXT = 4000
EXTRA_ARTIFACTS = (
    "quality_report.json", "quality_report.md", "evaluation.csv", "evaluation.json", "run_log.json", "run_log.md",
)


def tracking_uri(cfg: Config) -> str:
    return "sqlite:///" + (cfg.paths.mlflow_dir.resolve() / "mlflow.db").as_posix()


def artifact_root(cfg: Config) -> str:
    return (cfg.paths.mlflow_dir.resolve() / "artifacts").as_uri()


def get_client(cfg: Config) -> MlflowClient:
    cfg.paths.mlflow_dir.mkdir(parents=True, exist_ok=True)
    return MlflowClient(tracking_uri=tracking_uri(cfg))


def ensure_experiment(client: MlflowClient, cfg: Config) -> str:
    existing = client.get_experiment_by_name(cfg.experiment_name)
    if existing is not None:
        return existing.experiment_id
    return client.create_experiment(cfg.experiment_name, artifact_location=artifact_root(cfg))


def _clean_key(key: str) -> str:
    return re.sub(r"[^\w\-. /]", "_", str(key))


def _short(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 3] + "..."


def build_params(cfg: Config, state: PipelineState) -> dict[str, str]:
    params = {
        "target": cfg.target.name,
        "procedure_version": cfg.procedure_version,
        "seed": cfg.seed,
        "factor_method": cfg.model_params.factor_method,
        "min_train_months": cfg.evaluation.min_train_months,
        "eval_months": ",".join(cfg.evaluation.eval_months),
        "baselines": ",".join(cfg.evaluation.baselines),
        "mobility_months": ",".join(cfg.coverage.mobility_months),
        "months_to_estimate": ",".join(cfg.coverage.months_to_estimate),
        "exclude_countries": ",".join(cfg.target.exclude_countries),
        "mobility_source": f"{cfg.sources.mobility.file}:{cfg.sources.mobility.sheet}",
        "migration_source": f"{cfg.sources.migration.file}:{cfg.sources.migration.sheet}",
        "visitor_types": ",".join(cfg.sources.migration.visitor_types),
    }
    if state.source_fingerprint:
        params["source_fingerprint"] = state.source_fingerprint
    return {_clean_key(k): _short(str(v)) for k, v in params.items()}


def build_metrics(state: PipelineState) -> dict[str, float]:
    metrics = {
        _clean_key(k): float(v) for k, v in state.metrics.items()
        if isinstance(v, (int, float)) and math.isfinite(v)
    }
    if state.check_results:
        for status in CheckStatus:
            metrics[f"checks_{status.value}"] = float(sum(r.status is status for r in state.check_results))
    return metrics


def build_tags(state: PipelineState) -> dict[str, str]:
    outcomes = {
        RunStatus.SUCCESS: "published" if state.published else "completed",
        RunStatus.REJECTED: "rejected",
        RunStatus.FAILED_CHECKS: "failed_checks",
        RunStatus.FAILED: "failed",
    }
    tags = {
        "run_id": state.context.run_id,
        "git_commit": state.context.git_commit,
        "started_at": state.context.started_at.isoformat(timespec="seconds"),
        "outcome": outcomes[state.status],
        "published": str(state.published).lower(),
        "completed_stages": ",".join(state.completed_stages),
        "warning_count": str(len(state.warnings)),
        "alert_count": str(len(state.alerts)),
    }
    if state.status is RunStatus.FAILED:
        tags["failure_cause"] = "; ".join(state.errors)
    elif state.status is RunStatus.FAILED_CHECKS:
        names = ", ".join(r.name for r in state.check_results if r.blocks_pipeline)
        tags["failure_cause"] = f"critical checks failed: {names}"
    return {k: _short(v) for k, v in tags.items()}


def write_run_files(cfg: Config, state: PipelineState) -> list[Path]:
    work_dir = state.context.work_dir
    work_dir.mkdir(parents=True, exist_ok=True)
    files = []

    config_path = work_dir / "config.json"
    config_path.write_text(to_json(cfg.model_dump(mode="json")), encoding="utf-8")
    files.append(config_path)

    if hasattr(state.estimates, "to_csv"):
        estimates_path = work_dir / "estimates.csv"
        if not estimates_path.is_file():
            state.estimates.to_csv(estimates_path, index=False)
        files.append(estimates_path)

    model = to_plain(state.model)
    if isinstance(model, dict):
        model_path = work_dir / "model_params.json"
        model_path.write_text(to_json(model), encoding="utf-8")
        files.append(model_path)

    files += [work_dir / name for name in EXTRA_ARTIFACTS if (work_dir / name).is_file()]
    if state.published_dir is not None:
        files.append(state.published_dir / META_FILE)
    return files


def record_run(cfg: Config, state: PipelineState) -> str:
    client = get_client(cfg)
    experiment_id = ensure_experiment(client, cfg)
    files = write_run_files(cfg, state)
    failed = state.status in (RunStatus.FAILED, RunStatus.FAILED_CHECKS)

    run = client.create_run(experiment_id, run_name=state.context.run_id, tags=build_tags(state))
    run_id = run.info.run_id
    try:
        for key, value in build_params(cfg, state).items():
            client.log_param(run_id, key, value)
        for key, value in build_metrics(state).items():
            client.log_metric(run_id, key, value)
        for path in files:
            client.log_artifact(run_id, str(path))
    finally:
        client.set_terminated(run_id, status="FAILED" if failed else "FINISHED")
    return run_id
