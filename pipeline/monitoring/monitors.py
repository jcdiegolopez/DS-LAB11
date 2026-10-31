"""Three monitors that run after every execution.

They only raise alerts: a monitor never stops a run, never changes its status and never
blocks a publication. Blocking is the job of the quality checks and the acceptance rule.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pipeline.checks.common import MOBILITY_KEY, frames, month_labels, used_migration
from pipeline.config import Config
from pipeline.contracts import PipelineState
from pipeline.publish.store import ESTIMATES_FILE, META_FILE

OK, ALERT, SKIPPED = "ok", "alert", "skipped"
PROFILED_NULLS = ("visitantes", "pais", "permanencia_prom")


@dataclass
class MonitorResult:
    name: str
    status: str
    detail: str
    alerts: list[str] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_alerts(cls, name: str, alerts: list[str], ok_detail: str, info: dict) -> "MonitorResult":
        if alerts:
            return cls(name, ALERT, f"{len(alerts)} alert(s)", alerts, info)
        return cls(name, OK, ok_detail, [], info)


def _last_months(cfg: Config, raw) -> dict[str, str | None]:
    mobility, migration = frames(raw)
    mobility_months = month_labels(mobility["anio"], mobility["mes"]).dropna()
    migration_months = used_migration(cfg, migration)["period"].dropna()
    return {
        "mobility": mobility_months.max() if len(mobility_months) else None,
        "migration": migration_months.max() if len(migration_months) else None,
    }


def freshness(cfg: Config, state: PipelineState, previous_run: dict | None, approved_meta: dict | None) -> MonitorResult:
    """Is each source up to the last period the configuration expects, and is the approved version current?"""
    name = "freshness"
    if state.raw is None:
        return MonitorResult(name, SKIPPED, "the sources were not read")
    try:
        latest = _last_months(cfg, state.raw)
    except (KeyError, ValueError, TypeError) as exc:
        return MonitorResult(name, SKIPPED, f"cannot read the periods of the sources: {exc}")

    expected = cfg.coverage.expected_last_period.model_dump()
    alerts = []
    for source, last in latest.items():
        if last is None:
            alerts.append(f"{source}: no valid periods")
        elif last < expected[source]:
            alerts.append(f"{source}: data ends at {last}, expected up to {expected[source]} (source not updated)")
        elif last > expected[source]:
            alerts.append(
                f"{source}: data reaches {last}, past the configured {expected[source]}; "
                "update coverage in config.yaml to use it"
            )

    info: dict[str, Any] = {"latest_period": latest, "expected_last_period": expected}
    if previous_run is not None and state.source_fingerprint:
        info["sources_changed_since_previous_run"] = previous_run.get("source_fingerprint") != state.source_fingerprint
    if approved_meta is not None:
        info["approved_version"] = approved_meta.get("run_id")
        info["approved_generated_at"] = approved_meta.get("generated_at")
        approved_sources = approved_meta.get("source_fingerprint")
        if state.source_fingerprint and approved_sources and approved_sources != state.source_fingerprint and not state.published:
            alerts.append(
                f"the approved version {approved_meta.get('run_id')} was built from different sources "
                "and this run did not replace it"
            )
    return MonitorResult.from_alerts(name, alerts, "sources reach the expected periods", info)


def quality_profile(cfg: Config, raw) -> dict | None:
    """Counts the quality monitor compares between runs. None when the columns are not usable."""
    if raw is None:
        return None
    try:
        mobility, migration = frames(raw)
        months = month_labels(mobility["anio"], mobility["mes"]).dropna()
        return {
            "mobility_rows": int(len(mobility)),
            "migration_rows": int(len(migration)),
            "missing_ratio": {
                c: round(float(mobility[c].isna().mean()), 6) if len(mobility) else 0.0
                for c in PROFILED_NULLS if c in mobility.columns
            },
            "duplicated_keys": int(mobility.duplicated(subset=MOBILITY_KEY, keep=False).sum()),
            "zero_visitors": int((mobility["visitantes"] == 0).sum()),
            "mobility_months": sorted(set(months)),
            "migration_months": int(used_migration(cfg, migration)["period"].nunique()),
        }
    except (KeyError, ValueError, TypeError):
        return None


def _change(old: float, new: float) -> float:
    return abs(new - old) / old if old else (0.0 if new == old else float("inf"))


def quality(cfg: Config, profile: dict | None, previous: tuple[str, dict] | None) -> MonitorResult:
    """Did missing values, duplicates or coverage get worse than in the previous run?"""
    name = "quality"
    if profile is None:
        return MonitorResult(name, SKIPPED, "no quality profile: the sources were not read or lack required columns")
    if previous is None:
        return MonitorResult(name, OK, "no previous run to compare with; this profile is the baseline", info={"profile": profile})

    previous_id, before = previous
    limits = cfg.monitoring
    alerts = []

    for key in ("mobility_rows", "migration_rows"):
        change = _change(before[key], profile[key])
        if change > limits.max_row_change_ratio:
            alerts.append(f"{key}: {before[key]} -> {profile[key]} ({change:.1%}, limit {limits.max_row_change_ratio:.0%})")

    for column, ratio in profile["missing_ratio"].items():
        old = before.get("missing_ratio", {}).get(column, 0.0)
        if ratio - old > limits.max_missing_ratio_increase:
            alerts.append(f"missing '{column}': {old:.2%} -> {ratio:.2%}")

    if profile["duplicated_keys"] > before["duplicated_keys"]:
        alerts.append(f"duplicated keys: {before['duplicated_keys']} -> {profile['duplicated_keys']}")

    lost = sorted(set(before["mobility_months"]) - set(profile["mobility_months"]))
    if lost:
        alerts.append(f"mobility months no longer present: {', '.join(lost)}")
    if profile["migration_months"] < before["migration_months"]:
        alerts.append(f"migration months: {before['migration_months']} -> {profile['migration_months']}")

    info = {"compared_with": previous_id, "profile": profile}
    return MonitorResult.from_alerts(name, alerts, f"no quality loss against run {previous_id}", info)


def _estimated(estimates: pd.DataFrame) -> pd.DataFrame:
    rows = estimates.loc[:, ["subdestination", "period", "value", "kind"]].copy()
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    return rows


def results(cfg: Config, state: PipelineState, previous_approved: tuple[str, pd.DataFrame] | None) -> MonitorResult:
    """Impossible values in the estimates, and large changes month to month or against the approved version."""
    name = "results"
    if state.estimates is None:
        return MonitorResult(name, SKIPPED, "the run produced no estimates")

    limit = cfg.thresholds.max_period_change_ratio
    rows = _estimated(state.estimates)
    alerts = []

    present = rows["value"].dropna()
    non_finite = int((~np.isfinite(present)).sum())
    negative = int((present < 0).sum())
    if non_finite:
        alerts.append(f"{non_finite} non-finite values")
    if negative:
        alerts.append(f"{negative} negative values")

    # Month-to-month change only between consecutive calendar months, and only where an estimate
    # is involved: the observed series is the data, the estimate is what is being watched.
    for sub, series in rows.sort_values("period").groupby("subdestination", sort=False):
        series = series.set_index("period")
        for period, row in series.iterrows():
            prev = (pd.Period(period, freq="M") - 1).strftime("%Y-%m")
            if prev not in series.index or "estimated" not in (row["kind"], series.at[prev, "kind"]):
                continue
            old, new = series.at[prev, "value"], row["value"]
            if pd.notna(old) and pd.notna(new) and _change(old, new) > limit:
                alerts.append(f"{sub} {prev} -> {period}: {old:,.0f} -> {new:,.0f} ({_change(old, new):.0%}, limit {limit:.0%})")

    info: dict[str, Any] = {"change_limit": limit}
    if previous_approved is not None:
        version, approved = previous_approved
        info["compared_with_approved"] = version
        old = _estimated(approved)
        merged = rows[rows["kind"] == "estimated"].merge(
            old[old["kind"] == "estimated"], on=["subdestination", "period"], suffixes=("", "_approved")
        )
        for row in merged.itertuples(index=False):
            if pd.notna(row.value) and pd.notna(row.value_approved) and _change(row.value_approved, row.value) > limit:
                alerts.append(
                    f"{row.subdestination} {row.period}: {row.value_approved:,.0f} in approved {version} "
                    f"-> {row.value:,.0f} ({_change(row.value_approved, row.value):.0%})"
                )
    return MonitorResult.from_alerts(name, alerts, "no impossible values and no change above the limit", info)


def read_approved(approved_dir: Path, version: str | None) -> tuple[dict | None, pd.DataFrame | None]:
    if version is None:
        return None, None
    folder = approved_dir / version
    try:
        meta = json.loads((folder / META_FILE).read_text(encoding="utf-8"))
        estimates = pd.read_csv(folder / ESTIMATES_FILE)
    except (OSError, ValueError):
        return None, None
    return meta, estimates
