"""Guard against names that are used but never defined - the game layer cannot be imported by
tests, so a missing import only shows up as a NameError at runtime (as prompt_summary did)."""
import ast
import builtins
from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).resolve().parents[1] / "scripts").glob("*.py"))
SELF_NAMES = {"__name__", "__file__", "__doc__", "__package__", "__builtins__", "__class__"}


def _defined_names(tree):
    """Everything the module could possibly have bound: imports, defs/classes, assignments,
    arguments, with/except/for targets, globals. Deliberately over-inclusive - this only has
    to catch names that are never bound anywhere."""
    names = set(dir(builtins)) | SELF_NAMES
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            arguments = getattr(node, "args", None)
            if arguments is not None:
                for arg in (arguments.args + arguments.kwonlyargs):
                    names.add(arg.arg)
                if arguments.vararg is not None:
                    names.add(arguments.vararg.arg)
                if arguments.kwarg is not None:
                    names.add(arguments.kwarg.arg)
        elif isinstance(node, ast.Lambda):
            for arg in (node.args.args + node.args.kwonlyargs):
                names.add(arg.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.Global):
            names.update(node.names)
    return names


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda path: path.name)
def test_every_name_used_is_defined(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    defined = _defined_names(tree)
    used = {node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    assert sorted(used - defined) == [], "{} uses undefined names".format(path.name)
