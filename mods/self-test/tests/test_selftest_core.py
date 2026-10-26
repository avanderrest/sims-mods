"""Tests for the self-test harness itself. No game imports: selftest_core is plain logic."""
import pytest

import selftest_core as core


def _registry():
    registry = core.Registry()
    return registry


def test_registers_and_runs_checks():
    registry = _registry()
    suite = registry.suite("demo", "Demo suite")

    @suite.check("passes plainly")
    def _plain(_context):
        return None

    @suite.check("passes with detail")
    def _with_detail(_context):
        return "3 things found"

    @suite.check("returns (True, detail)")
    def _tuple(_context):
        return True, "fine"

    @suite.check("fails")
    def _fails(_context):
        raise core.CheckFailed("expected something else")

    @suite.check("skips")
    def _skips(_context):
        raise core.SkipCheck("nothing here to check")

    @suite.check("raises unexpectedly")
    def _boom(_context):
        raise ValueError("oops")

    results = registry.run()

    assert [r.status for r in results] == [core.PASS, core.PASS, core.PASS, core.FAIL, core.SKIP, core.FAIL]
    assert results[1].detail == "3 things found"
    assert results[2].detail == "fine"
    assert results[3].detail == "expected something else"
    assert results[4].detail == "nothing here to check"
    assert "ValueError: oops" in results[5].detail


def test_tuple_false_is_a_failure():
    registry = _registry()
    suite = registry.suite("demo")

    @suite.check("tuple failure")
    def _tuple(_context):
        return False, "not as expected"

    results = registry.run()
    assert results[0].status == core.FAIL
    assert results[0].detail == "not as expected"


def test_unexpected_exception_is_logged_and_does_not_stop_the_run():
    registry = _registry()
    suite = registry.suite("demo")
    logged = []

    @suite.check("explodes")
    def _boom(_context):
        raise RuntimeError("boom")

    @suite.check("still runs")
    def _after(_context):
        return None

    results = registry.run(log_exception=lambda text: logged.append(text))
    assert [r.status for r in results] == [core.FAIL, core.PASS]
    assert logged and "demo" in logged[0]


def test_order_follows_the_registration_order_and_selection():
    registry = _registry()
    for name in ("first", "second"):
        suite = registry.suite(name)
        for index in (1, 2):
            def _check(_context, name=name, index=index):
                return "{}-{}".format(name, index)
            suite.add("check {}".format(index), _check)

    assert [r.line() for r in registry.run()] == [
        "[PASS] first: check 1 - first-1",
        "[PASS] first: check 2 - first-2",
        "[PASS] second: check 1 - second-1",
        "[PASS] second: check 2 - second-2",
    ]

    assert [r.line() for r in registry.run("second")] == [
        "[PASS] second: check 1 - second-1",
        "[PASS] second: check 2 - second-2",
    ]
    assert [r.line() for r in registry.run(["first"])][0] == "[PASS] first: check 1 - first-1"
    assert len(registry.run("*")) == 4


def test_unknown_selection_raises_a_useful_error():
    registry = _registry()
    registry.suite("known")
    with pytest.raises(ValueError) as info:
        registry.run("typo")
    assert "typo" in str(info.value)
    assert "known" in str(info.value)


def test_counts_and_summary():
    results = [
        core.Result("a", "one", core.PASS),
        core.Result("a", "two", core.PASS, "detail"),
        core.Result("a", "three", core.FAIL, "bad"),
        core.Result("a", "four", core.SKIP, "not here"),
    ]
    assert core.counts(results) == {"PASS": 2, "FAIL": 1, "SKIP": 1, "total": 4}
    summary = core.summary(results)
    assert "2 passed" in summary
    assert "1 failed" in summary
    assert "1 skipped" in summary
    assert "4 checks" in summary
    assert core.failures(results) == ["[FAIL] a: three - bad"]


def test_summary_says_so_when_nothing_failed():
    results = [core.Result("a", "one", core.PASS)]
    assert "fix the FAIL" not in core.summary(results)


def test_report_is_serialisable():
    results = [core.Result("a", "one", core.PASS, "detail"),
               core.Result("a", "two", core.FAIL, "bad")]
    data = core.report(results, "2026-10-26T12:00:00")
    assert data["when"] == "2026-10-26T12:00:00"
    assert (data["passed"], data["failed"], data["skipped"], data["total"]) == (1, 1, 0, 2)
    assert data["results"][1] == {"suite": "a", "check": "two", "status": "FAIL", "detail": "bad"}
    import json
    assert json.loads(json.dumps(data))["results"][0]["detail"] == "detail"


# --- command listing (sims4.commands.describe returns (name, description, usage)) ---
def test_command_names_reads_describe_tuples():
    assert core.command_names([("houserules.hello", "", ""),
                               ("houserules.npc.tick", "Runs", "")]) == {
        "houserules.hello", "houserules.npc.tick"}


def test_command_names_is_case_insensitive_and_forgiving():
    class _Info:
        name = "houserules.other"

    assert core.command_names(["HouseRules.Hello", _Info(), ("",)]) == {
        "houserules.hello", "houserules.other"}


def test_command_names_of_an_unreadable_listing_is_empty():
    assert core.command_names(None) == set()
    assert core.command_names([]) == set()
