"""Self-test harness - pure logic (no game imports, covered by tests).

The suites in selftest_checks.py register named checks with a Registry; running a suite
calls every check in turn and records PASS / FAIL / SKIP. A check signals its result like
this:

    return "detail shown after the name"   -> PASS with a detail
    return None                            -> PASS
    raise CheckFailed("what is wrong")     -> FAIL
    raise SkipCheck("why it doesn't apply") -> SKIP

Anything else a check raises is a FAIL too, so one broken check can never stop the run
(and the runner gets the traceback through log_exception).

Output is one line per check, then a summary. The same lines go to the cheat console and
to Mods/HouseRules/logs/self-test.log, and the results are also written as JSON.
"""

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


def command_names(entries):
    """Command names from sims4.commands.describe() results.

    describe() returns (name, description, usage) tuples (see help_command.py), but stay
    forgiving so a game build that returns plain names or objects still works.
    """
    names = set()
    for entry in entries or ():
        name = entry
        if isinstance(entry, (tuple, list)):
            name = entry[0] if entry else None
        elif not isinstance(entry, str):
            name = getattr(entry, "name", entry)
        if name:
            names.add(str(name).lower())
    return names


class CheckFailed(Exception):
    """A check failed in an expected way; the message is shown in the console."""


class SkipCheck(Exception):
    """A check doesn't apply here (no clubs, no local LLM running, ...)."""


class Result:
    __slots__ = ("suite", "check", "status", "detail")

    def __init__(self, suite, check, status, detail=""):
        self.suite = suite
        self.check = check
        self.status = status
        self.detail = detail or ""

    def line(self):
        text = "[{}] {}: {}".format(self.status, self.suite, self.check)
        if self.detail:
            text += " - " + self.detail
        return text

    def as_dict(self):
        return {"suite": self.suite, "check": self.check,
                "status": self.status, "detail": self.detail}


class Suite:
    def __init__(self, name, title=""):
        self.name = name
        self.title = title or name
        self.checks = []

    def check(self, description):
        """Decorator: register a check with a human-readable description."""
        def register(func):
            self.checks.append((description, func))
            return func
        return register

    def add(self, description, func):
        self.checks.append((description, func))
        return func

    def __len__(self):
        return len(self.checks)


class Registry:
    def __init__(self):
        self._suites = {}

    def suite(self, name, title=""):
        if name not in self._suites:
            self._suites[name] = Suite(name, title)
        return self._suites[name]

    def names(self):
        return list(self._suites)

    def __len__(self):
        return len(self._suites)

    def selected(self, selected=None):
        """Resolve a comma-separated selection ("hardmode,social") or a list of suite names.

        Raises ValueError naming any unknown suite, so a typo never silently runs nothing.
        """
        if selected is None or selected == "" or selected == "*":
            return list(self._suites.values())
        if isinstance(selected, str):
            names = [part.strip() for part in selected.split(",") if part.strip()]
        else:
            names = list(selected)
        unknown = [name for name in names if name not in self._suites]
        if unknown:
            raise ValueError("unknown suite(s): {} (known: {})".format(
                ", ".join(unknown), ", ".join(self._suites) or "none"))
        return [self._suites[name] for name in names]

    def run(self, selected=None, context=None, log_exception=None):
        """Run every check in the selected suites. Returns an ordered list of Results."""
        results = []
        for suite in self.selected(selected):
            for description, func in suite.checks:
                try:
                    detail = func(context)
                    results.append(Result(suite.name, description, PASS, _detail(detail)))
                except SkipCheck as e:
                    results.append(Result(suite.name, description, SKIP, str(e)))
                except CheckFailed as e:
                    results.append(Result(suite.name, description, FAIL, str(e)))
                except Exception as e:
                    if log_exception is not None:
                        log_exception("check {}.{}".format(suite.name, description))
                    results.append(Result(suite.name, description, FAIL,
                                          "{}: {}".format(type(e).__name__, e)))
        return results


def _detail(value):
    """Checks may return None, a string, or (ok, detail)."""
    if value is None:
        return ""
    if isinstance(value, tuple):
        ok, detail = value
        if not ok:
            raise CheckFailed(str(detail) or "check returned a failure")
        return str(detail or "")
    return str(value)


def counts(results):
    """{'PASS': n, 'FAIL': n, 'SKIP': n, 'total': n}."""
    out = {PASS: 0, FAIL: 0, SKIP: 0}
    for result in results:
        out[result.status] = out.get(result.status, 0) + 1
    out["total"] = len(results)
    return out


def summary(results):
    c = counts(results)
    text = "Self-test: {} passed, {} failed, {} skipped ({} checks)".format(
        c[PASS], c[FAIL], c[SKIP], c["total"])
    failures = c[FAIL]
    if failures:
        text += " - fix the FAIL lines above"
    return text


def failures(results):
    return [result.line() for result in results if result.status == FAIL]


def report(results, when):
    """Serialisable report for Mods/HouseRules/data/self_test_last.json."""
    c = counts(results)
    return {
        "when": when,
        "passed": c[PASS],
        "failed": c[FAIL],
        "skipped": c[SKIP],
        "total": c["total"],
        "results": [result.as_dict() for result in results],
    }
