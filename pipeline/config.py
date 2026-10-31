from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

Month = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Paths(Strict):
    data_dir: Path
    work_dir: Path
    approved_dir: Path
    mlflow_dir: Path


class MobilitySource(Strict):
    file: str
    sheet: str


class MigrationSource(Strict):
    file: str
    sheet: str
    visitor_types: list[str]


class Sources(Strict):
    mobility: MobilitySource
    migration: MigrationSource


class Target(Strict):
    name: str
    unit: str
    granularity: str
    subdestinations: list[str]
    exclude_countries: list[str] = []


class LastPeriod(Strict):
    mobility: Month
    migration: Month


class Coverage(Strict):
    mobility_months: list[Month]
    months_to_estimate: list[Month]
    migration_first_period: Month
    expected_last_period: LastPeriod

    @model_validator(mode="after")
    def check_months(self) -> "Coverage":
        observed = self.mobility_months
        if observed != sorted(set(observed)):
            raise ValueError("mobility_months must be unique and in ascending order")
        overlap = set(observed) & set(self.months_to_estimate)
        if overlap:
            raise ValueError(f"months_to_estimate overlap with observed months: {sorted(overlap)}")
        beyond = [m for m in self.months_to_estimate if m > self.expected_last_period.migration]
        if beyond:
            raise ValueError(f"no migration data to estimate {beyond}")
        return self


class Evaluation(Strict):
    min_train_months: int
    eval_months: list[Month]
    baselines: list[Literal["last_observed", "prior_mean"]]

    @model_validator(mode="after")
    def check_values(self) -> "Evaluation":
        if self.min_train_months < 1:
            raise ValueError("min_train_months must be at least 1")
        if not self.baselines:
            raise ValueError("at least one baseline is required")
        return self


class Thresholds(Strict):
    max_missing_ratio: float
    max_mae: float | None = None
    max_mae_ratio_vs_baseline: float | None = None
    max_period_change_ratio: float


class Monitoring(Strict):
    max_row_change_ratio: float = 0.2
    max_missing_ratio_increase: float = 0.01

    @model_validator(mode="after")
    def check_values(self) -> "Monitoring":
        if self.max_row_change_ratio < 0 or self.max_missing_ratio_increase < 0:
            raise ValueError("monitoring tolerances must be non-negative")
        return self


class ModelParams(Strict):
    factor_method: Literal["ratio_of_sums", "mean_of_ratios"]


class Config(Strict):
    seed: int
    experiment_name: str
    procedure_version: str
    paths: Paths
    sources: Sources
    target: Target
    coverage: Coverage
    evaluation: Evaluation
    thresholds: Thresholds
    model_params: ModelParams
    monitoring: Monitoring = Monitoring()

    @model_validator(mode="after")
    def check_evaluation_months(self) -> "Config":
        observed = self.coverage.mobility_months
        last_migration = self.coverage.expected_last_period.migration
        for month in self.evaluation.eval_months:
            if month not in observed:
                raise ValueError(f"eval month {month} has no observed mobility data")
            if month > last_migration:
                raise ValueError(f"eval month {month} has no migration data")
            prior = sum(1 for m in observed if m < month)
            if prior < self.evaluation.min_train_months:
                raise ValueError(
                    f"eval month {month} has {prior} prior observed months, "
                    f"fewer than min_train_months={self.evaluation.min_train_months}"
                )
        return self


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return Config.model_validate(raw)
