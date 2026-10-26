"""Self-test - in-game test suite, run from the cheat console.

With a save loaded and a sim selected, press Ctrl+Shift+C and type:

    houserules.test                 run every suite
    houserules.test hardmode        only one suite (comma-separated for several)
    houserules.test.run gates       same thing
    houserules.test.list            list the suites and how many checks each has

Each check prints one [PASS] / [FAIL] / [SKIP] line in the console and the same lines go
to Mods/HouseRules/logs/self-test.log. The last run's results are also written to
Mods/HouseRules/data/self_test_last.json, so a failing check can be looked at later
without copying the console.

The suites are in selftest_checks.py; this file only wires them to cheat commands.
The tests are meant for a save you don't mind changing: they add and then remove a debt,
a market sale, a routine entry and a royal flag (see the checks). Nothing is saved by
the harness itself beyond those round-trips and the two report files above.
"""
import datetime
import os

import sims4.commands

import selftest_checks
import selftest_core
import selftest_live as live
import selftest_log

REGISTRY = selftest_checks.REGISTRY
REPORT_PATH = os.path.join(live.DATA_DIR, "self_test_last.json")


def _write_report(results, when):
    try:
        live.save_json(REPORT_PATH, selftest_core.report(results, when))
    except Exception:
        selftest_log.log_exception("writing the self-test report")


def _run(output, selected):
    started = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        results = REGISTRY.run(selected, log_exception=selftest_log.log_exception)
    except ValueError as e:
        output(str(e))
        return
    if not results:
        output("No checks are registered.")
        return
    for result in results:
        line = result.line()
        output(line)
        selftest_log.log("result " + line)
    summary = selftest_core.summary(results)
    output(summary)
    selftest_log.log("summary " + summary)
    failed = selftest_core.failures(results)
    if failed:
        output("Failures ({}):".format(len(failed)))
        for line in failed:
            output("  " + line)
    output("Log: {}".format(live.log_path("self-test")))
    output("Report: {}".format(REPORT_PATH))
    _write_report(results, started)


@sims4.commands.Command("houserules.test", "houserules.test.run",
                        command_type=sims4.commands.CommandType.Live)
def selftest_run(suite: str = "", _connection=None):
    """Run the in-game test suite. Optional argument: a suite name (or a comma-separated list)."""
    _run(sims4.commands.CheatOutput(_connection), suite.strip() or None)


@sims4.commands.Command("houserules.test.list", command_type=sims4.commands.CommandType.Live)
def selftest_list(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    suites = REGISTRY.selected(None)
    total = sum(len(item) for item in suites)
    output("Self-test suites ({} checks in total):".format(total))
    for item in suites:
        output("  {}: {} checks - {}".format(item.name, len(item), item.title))
    output("Run them all with houserules.test, or one with houserules.test <suite>.")


selftest_log.log("self-test loaded: run houserules.test in the cheat console")
