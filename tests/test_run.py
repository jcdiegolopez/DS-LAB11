from pipeline.contracts import CheckResult, CheckStatus, RunStatus
from pipeline.run import execute


def test_all_stages_run_in_order(cfg):
    order = []
    stages = [(n, lambda c, s, n=n: order.append(n)) for n in ("a", "b", "c")]
    state = execute(cfg, stages)
    assert order == ["a", "b", "c"]
    assert state.completed_stages == ["a", "b", "c"]
    assert state.status is RunStatus.SUCCESS


def test_critical_check_error_stops_before_later_stages(cfg):
    def failing_check(c, s):
        s.check_results.append(CheckResult("columns", CheckStatus.ERROR, "missing column"))

    later = []
    stages = [("validate", failing_check), ("publish", lambda c, s: later.append(1))]
    state = execute(cfg, stages)
    assert state.status is RunStatus.FAILED_CHECKS
    assert later == []
    assert state.completed_stages == ["validate"]


def test_non_critical_error_does_not_stop(cfg):
    def soft_check(c, s):
        s.check_results.append(CheckResult("coverage", CheckStatus.ERROR, "gap", critical=False))

    state = execute(cfg, [("validate", soft_check), ("publish", lambda c, s: None)])
    assert state.status is RunStatus.SUCCESS
    assert state.completed_stages == ["validate", "publish"]


def test_exception_marks_run_failed_and_keeps_previous_stages(cfg):
    def boom(c, s):
        raise ValueError("bad input")

    state = execute(cfg, [("read", lambda c, s: None), ("fit", boom)])
    assert state.status is RunStatus.FAILED
    assert state.completed_stages == ["read"]
    assert state.errors == ["fit: bad input"]
    assert state.metrics == {}


def test_missing_stage_module_fails_the_run_with_a_clear_error(cfg):
    state = execute(cfg, [("read", lambda c, s: None), ("fit", "pipeline.stages.does_not_exist")])
    assert state.status is RunStatus.FAILED
    assert state.completed_stages == ["read"]
    assert state.errors[0].startswith("fit: No module named")


def test_each_run_gets_its_own_work_dir(cfg):
    first = execute(cfg, [])
    second = execute(cfg, [])
    assert first.context.run_id != second.context.run_id
    assert first.context.work_dir.is_dir() and second.context.work_dir.is_dir()
