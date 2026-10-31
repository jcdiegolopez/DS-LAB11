from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

ESTIMATE_COLUMNS = ("target", "subdestination", "period", "value", "unit", "kind")
STAMPED_COLUMNS = ("run_id", "generated_at", "procedure_version")
VALID_KINDS = frozenset({"observed", "estimated"})


class CheckStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class RunStatus(str, Enum):
    SUCCESS = "success"
    REJECTED = "rejected"
    FAILED_CHECKS = "failed_checks"
    FAILED = "failed"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str
    critical: bool = True

    @property
    def blocks_pipeline(self) -> bool:
        return self.critical and self.status is CheckStatus.ERROR


@dataclass(frozen=True)
class RunContext:
    run_id: str
    started_at: datetime
    git_commit: str
    work_dir: Path


@dataclass
class PipelineState:
    context: RunContext
    source_fingerprint: str | None = None
    raw: Any = None
    prepared: Any = None
    model: Any = None
    estimates: Any = None
    metrics: dict[str, float] = field(default_factory=dict)
    accepted: bool | None = None
    published: bool = False
    published_dir: Path | None = None
    check_results: list[CheckResult] = field(default_factory=list)
    completed_stages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: RunStatus = RunStatus.SUCCESS
