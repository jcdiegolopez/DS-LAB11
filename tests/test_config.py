from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from pipeline.config import load_config

ROOT = Path(__file__).resolve().parent.parent


def write_variant(tmp_path, mutate):
    data = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "variant.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_default_config_loads():
    cfg = load_config(ROOT / "config.yaml")
    assert cfg.seed == 42
    assert len(cfg.target.subdestinations) == 3
    assert cfg.coverage.months_to_estimate == ["2026-01", "2026-02"]


def test_unknown_key_is_rejected(tmp_path):
    path = write_variant(tmp_path, lambda d: d.update(surprise=1))
    with pytest.raises(ValidationError):
        load_config(path)


def test_bad_month_format_is_rejected(tmp_path):
    path = write_variant(tmp_path, lambda d: d["coverage"].update(months_to_estimate=["2026-1"]))
    with pytest.raises(ValidationError):
        load_config(path)


def test_estimate_month_cannot_be_observed(tmp_path):
    path = write_variant(tmp_path, lambda d: d["coverage"].update(months_to_estimate=["2026-03"]))
    with pytest.raises(ValidationError, match="overlap"):
        load_config(path)


def test_observed_months_must_be_ascending(tmp_path):
    def swap(d):
        months = d["coverage"]["mobility_months"]
        months[0], months[1] = months[1], months[0]

    with pytest.raises(ValidationError, match="ascending"):
        load_config(write_variant(tmp_path, swap))


def test_eval_month_needs_observed_data(tmp_path):
    path = write_variant(tmp_path, lambda d: d["evaluation"].update(eval_months=["2026-01"]))
    with pytest.raises(ValidationError, match="no observed mobility"):
        load_config(path)


def test_eval_month_needs_migration_data(tmp_path):
    path = write_variant(tmp_path, lambda d: d["evaluation"].update(eval_months=["2026-07"]))
    with pytest.raises(ValidationError, match="no migration data"):
        load_config(path)


def test_eval_month_needs_enough_training_months(tmp_path):
    path = write_variant(tmp_path, lambda d: d["evaluation"].update(eval_months=["2025-10"]))
    with pytest.raises(ValidationError, match="min_train_months"):
        load_config(path)
