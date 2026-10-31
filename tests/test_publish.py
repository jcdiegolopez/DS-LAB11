import json

import numpy as np
import pytest

from pipeline.contracts import RunStatus
from pipeline.publish import runner
from pipeline.publish.restore import main as restore_main
from pipeline.publish.store import (
    ESTIMATES_FILE, META_FILE, current_version, list_versions, restore, validate_estimates,
)
from tests.helpers import make_estimates, make_state


def test_valid_estimates_pass():
    validate_estimates(make_estimates())


def test_missing_value_is_allowed_because_no_data_is_not_zero():
    estimates = make_estimates(value_jan=np.nan)
    validate_estimates(estimates)


@pytest.mark.parametrize("mutate, message", [
    (lambda df: df.drop(columns=["unit"]), "missing columns"),
    (lambda df: df.iloc[0:0], "empty"),
    (lambda df: df.assign(kind="guess"), "kind"),
    (lambda df: df.assign(period="2026-1"), "YYYY-MM"),
    (lambda df: df.assign(value=-1.0), "negative"),
    (lambda df: df.assign(value=np.inf), "non-finite"),
    (lambda df: df.assign(value="n/a"), "non-numeric"),
    (lambda df: df.assign(period="2026-01"), "not unique"),
])
def test_invalid_estimates_are_rejected(mutate, message):
    with pytest.raises(ValueError, match=message):
        validate_estimates(mutate(make_estimates()))


def test_accepted_run_publishes_a_complete_version_and_moves_the_pointer(cfg):
    state = make_state(cfg)
    runner.run(cfg, state)

    approved = cfg.paths.approved_dir
    assert state.published is True
    assert current_version(approved) == state.context.run_id
    assert list_versions(approved) == [state.context.run_id]

    version = approved / state.context.run_id
    meta = json.loads((version / META_FILE).read_text(encoding="utf-8"))
    assert meta["metrics"] == {"mae_isla_de_flores": 1606.0}
    assert meta["git_commit"] == "abc1234"
    assert meta["source_fingerprint"] == "a" * 64
    assert meta["model"] == {"Isla De Flores": 0.014846}

    published = (version / ESTIMATES_FILE).read_text(encoding="utf-8").splitlines()
    assert published[0] == "target,subdestination,period,value,unit,kind,run_id,generated_at,procedure_version"
    assert state.context.run_id in published[1]


@pytest.mark.parametrize("decision", [False, None])
def test_unauthorized_run_does_not_touch_the_approved_version(cfg, decision):
    first = make_state(cfg, run_id="run-1")
    runner.run(cfg, first)

    second = make_state(cfg, run_id="run-2", accepted=decision)
    runner.run(cfg, second)

    assert second.status is RunStatus.REJECTED
    assert second.published is False
    assert current_version(cfg.paths.approved_dir) == "run-1"
    assert list_versions(cfg.paths.approved_dir) == ["run-1"]


def test_invalid_estimates_leave_the_approved_version_untouched(cfg):
    runner.run(cfg, make_state(cfg, run_id="run-1"))

    bad = make_state(cfg, run_id="run-2", estimates=make_estimates(value_jan=-5.0))
    with pytest.raises(ValueError, match="negative"):
        runner.run(cfg, bad)

    assert current_version(cfg.paths.approved_dir) == "run-1"
    assert list_versions(cfg.paths.approved_dir) == ["run-1"]
    assert not any(p.name.startswith(".staging") for p in cfg.paths.approved_dir.iterdir())


def test_missing_estimates_raise(cfg):
    state = make_state(cfg)
    state.estimates = None
    with pytest.raises(ValueError, match="no estimates"):
        runner.run(cfg, state)


def test_new_version_keeps_the_previous_one_and_it_can_be_restored(cfg):
    runner.run(cfg, make_state(cfg, run_id="run-1"))
    runner.run(cfg, make_state(cfg, run_id="run-2", estimates=make_estimates(value_jan=4000.0)))
    approved = cfg.paths.approved_dir

    assert list_versions(approved) == ["run-1", "run-2"]
    assert current_version(approved) == "run-2"

    restore(approved, "run-1")
    assert current_version(approved) == "run-1"


def test_restore_rejects_unknown_and_incomplete_versions(cfg):
    runner.run(cfg, make_state(cfg, run_id="run-1"))
    approved = cfg.paths.approved_dir
    (approved / "broken").mkdir()
    (approved / "broken" / ESTIMATES_FILE).write_text("x", encoding="utf-8")

    for name in ("nope", "broken"):
        with pytest.raises(ValueError, match="not a complete approved version"):
            restore(approved, name)
    assert current_version(approved) == "run-1"


def test_restore_cli_lists_and_restores(cfg, config_path, capsys):
    runner.run(cfg, make_state(cfg, run_id="run-1"))
    runner.run(cfg, make_state(cfg, run_id="run-2"))

    assert restore_main(["--config", str(config_path), "--list"]) == 0
    listing = capsys.readouterr().out
    assert "* run-2" in listing and "  run-1" in listing

    assert restore_main(["--config", str(config_path), "--to", "run-1"]) == 0
    assert current_version(cfg.paths.approved_dir) == "run-1"
    assert restore_main(["--config", str(config_path), "--to", "missing"]) == 1
