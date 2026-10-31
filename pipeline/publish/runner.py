from __future__ import annotations

from datetime import datetime, timezone

from pipeline.config import Config
from pipeline.contracts import PipelineState, RunStatus
from pipeline.publish.store import set_current, stamp, validate_estimates, write_version
from pipeline.serialization import to_plain


def build_meta(cfg: Config, state: PipelineState, generated_at: datetime) -> dict:
    return {
        "run_id": state.context.run_id,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "procedure_version": cfg.procedure_version,
        "git_commit": state.context.git_commit,
        "target": cfg.target.name,
        "unit": cfg.target.unit,
        "source_fingerprint": state.source_fingerprint,
        "model": to_plain(state.model),
        "factor_method": cfg.model_params.factor_method,
        "seed": cfg.seed,
        "eval_months": cfg.evaluation.eval_months,
        "min_train_months": cfg.evaluation.min_train_months,
        "metrics": state.metrics,
        "checks": [
            {"name": r.name, "status": r.status.value, "critical": r.critical, "detail": r.detail}
            for r in state.check_results
        ],
        "warnings": state.warnings,
    }


def run(cfg: Config, state: PipelineState) -> None:
    if state.estimates is None:
        raise ValueError("there are no estimates to publish")

    if state.accepted is not True:
        reason = "rejected by the acceptance rule" if state.accepted is False else "no acceptance decision was made"
        state.warnings.append(f"version not published: {reason}")
        state.status = RunStatus.REJECTED
        return

    generated_at = datetime.now(timezone.utc)
    estimates = stamp(state.estimates, state.context.run_id, generated_at, cfg.procedure_version)
    validate_estimates(estimates)

    approved_dir = cfg.paths.approved_dir
    approved_dir.mkdir(parents=True, exist_ok=True)
    version_dir = write_version(approved_dir, state.context.run_id, estimates, build_meta(cfg, state, generated_at))
    set_current(approved_dir, state.context.run_id)

    state.published = True
    state.published_dir = version_dir
