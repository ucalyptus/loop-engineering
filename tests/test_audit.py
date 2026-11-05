"""Tests for the sensor audit (Gap 1): a check must detect failure."""
import tempfile
import unittest
from pathlib import Path

from loopctl.audit import audit_check, stub_python_source
from loopctl.cli import main as cli_main
from loopctl.manifest import Check, Limits, Manifest


def _make_workdir(calc_body):
    tmp = Path(tempfile.mkdtemp(prefix="loopctl-audit-"))
    (tmp / "calc.py").write_text(calc_body)
    (tmp / "test_calc.py").write_text(
        "import unittest, calc\n"
        "class T(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(calc.add(2, 3), 5)\n")
    return tmp


def _manifest(tmp, checks):
    return Manifest(path=tmp / "loop.toml", name="calc", goal="calc works",
                    workdir=tmp, checks=tuple(checks), actor="true",
                    actor_timeout_s=60, admission=(), require_approval=False,
                    fresh_clone=False, limits=Limits(),
                    decider=None, protected=())


class TestStub(unittest.TestCase):
    def test_functions_return_zero_and_init_passes(self):
        stubbed = stub_python_source(
            "def add(a, b):\n    return a + b\n\n"
            "class C:\n    def __init__(self):\n        self.x = 1\n")
        ns = {}
        exec(stubbed, ns)
        self.assertEqual(ns["add"](2, 3), 0)
        # __init__ must not return a value: constructing must succeed.
        ns["C"]()


class TestAuditCheck(unittest.TestCase):
    def test_unittest_check_is_strong(self):
        tmp = _make_workdir("def add(a, b):\n    return a + b\n")
        m = _manifest(tmp, [Check("add", "python3 -m unittest -q test_calc")])
        r = audit_check(m, m.checks[0])
        self.assertEqual(r["verdict"], "strong", r)

    def test_py_compile_check_is_vacuous(self):
        # A stubbed file still compiles: py_compile proves syntax, not behaviour.
        tmp = _make_workdir("def add(a, b):\n    return a + b\n")
        m = _manifest(tmp, [Check("compile", "python3 -m py_compile calc.py")])
        r = audit_check(m, m.checks[0])
        self.assertEqual(r["verdict"], "vacuous", r)

    def test_failing_baseline_is_inconclusive(self):
        tmp = _make_workdir("def add(a, b):\n    return a - b\n")
        m = _manifest(tmp, [Check("add", "python3 -m unittest -q test_calc")])
        r = audit_check(m, m.checks[0])
        self.assertEqual(r["verdict"], "inconclusive", r)

    def test_test_files_are_not_stubbed(self):
        # If tests were stubbed, a unittest check would pass vacuously.
        # This test is the same as strong, but guards the exclusion: the
        # mutated copy must still run the real test against stubbed code.
        tmp = _make_workdir("def add(a, b):\n    return a + b\n")
        m = _manifest(tmp, [Check("add", "python3 -m unittest -q test_calc")])
        r = audit_check(m, m.checks[0])
        self.assertEqual(r["verdict"], "strong", r)


class TestAuditCli(unittest.TestCase):
    def test_cli_exits_1_on_vacuous_and_0_on_strong(self):
        tmp = _make_workdir("def add(a, b):\n    return a + b\n")
        (tmp / "loop.toml").write_text(
            'name = "calc"\n'
            'goal = "calc works"\n'
            'workdir = "."\n'
            'actor = "true"\n'
            '[[checks]]\n'
            'name = "compile"\n'
            'run = "python3 -m py_compile calc.py"\n')
        self.assertEqual(cli_main(["audit", str(tmp / "loop.toml")]), 1)
        (tmp / "loop.toml").write_text(
            'name = "calc"\n'
            'goal = "calc works"\n'
            'workdir = "."\n'
            'actor = "true"\n'
            '[[checks]]\n'
            'name = "add"\n'
            'run = "python3 -m unittest -q test_calc"\n')
        self.assertEqual(cli_main(["audit", str(tmp / "loop.toml")]), 0)


if __name__ == "__main__":
    unittest.main()
