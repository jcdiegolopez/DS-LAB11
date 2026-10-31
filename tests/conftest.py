from pathlib import Path

import pytest
import yaml

from pipeline.config import Config, load_config

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def config_path(tmp_path) -> Path:
    data = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    data["paths"] = {
        "data_dir": str(tmp_path / "data"),
        "work_dir": str(tmp_path / "runs"),
        "approved_dir": str(tmp_path / "approved"),
        "mlflow_dir": str(tmp_path / "mlruns"),
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def cfg(config_path) -> Config:
    return load_config(config_path)
