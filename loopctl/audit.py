"""Sensor audit: prove each check can detect failure, not just pass.

A check that exits 0 is only a sensor if it also exits non-zero when the
code it is supposed to guard is broken. ``loopctl audit`` tests that
directly, with a mutation probe instead of a model judgement:

1. Run the check on an unmutated copy of the workdir (baseline).
2. Stub every implementation function in that copy to ``return 0``
   (``__init__`` to ``pass`` — returning a value there is illegal) and
   run the check again.
3. Verdict per check:
   - ``strong``: baseline passes, mutated fails — the check detects
     broken code.
   - ``vacuous``: baseline passes, mutated still passes — the check
     cannot tell broken code from working code. ``py_compile`` is the
     classic case: a stubbed file still compiles.
   - ``inconclusive``: baseline already fails, so the probe cannot tell
     whether the check detects failure or the code is just broken.
   - ``skipped``: no mutable Python files were found to stub.

Test files and check scripts are never stubbed: stubbing a test would
make the test itself vacuous, and stubbing a check script would break
the sensor rather than the code under test.
"""

from __future__ import annotations

import ast
import os
import shutil
import tempfile
from pathlib import Path

from .controller import _sh
from .manifest import Check, Manifest

IGNORE = shutil.ignore_patterns(".git", ".loop", "__pycache__", "*.egg-info", "build", "dist")


def stub_python_source(source: str) -> str:
    """Replace every function body with ``return 0`` (``pass`` for ``__init__``)."""

    class _Stub(ast.NodeTransformer):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
            self.generic_visit(node)
            node.body = [ast.Pass()] if node.name == "__init__" else [
                ast.Return(value=ast.Constant(value=0))]
            return node

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
            self.generic_visit(node)
            node.body = [ast.Pass()] if node.name == "__init__" else [
                ast.Return(value=ast.Constant(value=0))]
            return node

    tree = ast.parse(source)
    tree = _Stub().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def is_test_file(path: Path) -> bool:
    return path.name.startswith("test_") or path.name.endswith("_test.py") or "tests" in path.parts


def _check_script_files(check: Check) -> set[str]:
    """Files that *are* the check script, and so must not be stubbed.

    ``python3 check_card.py`` names a script: stubbing it would break the
    sensor, not the code under test. ``python3 -m py_compile calc.py``
    does not: ``calc.py`` there is the code under test, and ``-m`` means
    the following tokens are module arguments, not a script. So a
    ``-m`` command has no script file at all.
    """
    import shlex

    try:
        tokens = shlex.split(check.run)
    except ValueError:
        return set()
    if "-m" in tokens:
        return set()
    interpreters = {"python3", "python", "sh", "bash"}
    i = 0
    while i < len(tokens) and (tokens[i] in interpreters or tokens[i].endswith("/python3")):
        i += 1
    if i < len(tokens) and tokens[i].endswith(".py"):
        return {tokens[i]}
    return set()


def audit_check(m: Manifest, check: Check) -> dict:
    """Audit one check. Returns a dict with name, baseline, mutated, verdict, detail."""
    referenced = _check_script_files(check)
    with tempfile.TemporaryDirectory(prefix="loopctl-audit-") as tmp:
        copy = Path(tmp) / "work"
        shutil.copytree(m.workdir, copy, ignore=IGNORE)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        baseline, _ = _sh(check.run, copy, check.timeout_s, env=env)
        if baseline != 0:
            return {"name": check.name, "baseline": baseline, "mutated": None,
                    "verdict": "inconclusive",
                    "detail": "check fails on unmutated code, so the probe cannot judge it"}
        mutated_files = 0
        for py in sorted(copy.rglob("*.py")):
            rel = py.relative_to(copy)
            if is_test_file(rel) or rel.as_posix() in referenced or str(rel) in referenced:
                continue
            try:
                stubbed = stub_python_source(py.read_text())
            except (SyntaxError, ValueError):
                continue
            if stubbed != py.read_text():
                py.write_text(stubbed)
                mutated_files += 1
        if mutated_files == 0:
            return {"name": check.name, "baseline": baseline, "mutated": None,
                    "verdict": "skipped", "detail": "no mutable Python files found"}
        mutated, _ = _sh(check.run, copy, check.timeout_s, env=env)
        if mutated != 0:
            return {"name": check.name, "baseline": baseline, "mutated": mutated,
                    "verdict": "strong", "detail": "check fails on stubbed code"}
        return {"name": check.name, "baseline": baseline, "mutated": mutated,
                "verdict": "vacuous",
                "detail": "check still passes when implementation functions are stubbed to return 0"}


def audit_manifest(m: Manifest) -> list[dict]:
    """Audit every check in a manifest, in manifest order."""
    return [audit_check(m, c) for c in m.checks]
