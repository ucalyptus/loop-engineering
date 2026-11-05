"""Tests for the stdlib-shadow admission gate (Gap 1).

The shadow demo: an actor adds a one-line ``unittest.py`` that exits 0,
so every unittest check "passes" without running any test. The gate must
reject that file at admission, before any commit.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from loopctl.controller import Git, admit, check_worktree, stdlib_shadow_files
from loopctl.manifest import load

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def _git(cwd, *args):
    import os
    full = {**os.environ, **GIT_ENV}
    subprocess.run(["git", *args], cwd=cwd, check=True, env=full,
                   capture_output=True, text=True)


def _make_repo(with_shadow_committed=False):
    tmp = Path(tempfile.mkdtemp(prefix="loopctl-shadow-"))
    (tmp / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp / "test_calc.py").write_text(
        "import unittest, calc\n"
        "class T(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(calc.add(2, 3), 5)\n")
    if with_shadow_committed:
        (tmp / "unittest.py").write_text("# pre-existing, not actor-added\n")
    (tmp / "loop.toml").write_text(
        'name = "calc"\n'
        'goal = "calc works"\n'
        'workdir = "."\n'
        'actor = "true"\n'
        '[[checks]]\n'
        'name = "add"\n'
        'run = "python3 -m unittest -q test_calc"\n')
    _git(tmp, "init", "-q")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-qm", "initial")
    return tmp


class TestStdlibShadowHelper(unittest.TestCase):
    def test_root_stdlib_names_flagged(self):
        self.assertEqual(stdlib_shadow_files(["unittest.py", "json.py"]),
                         ["json.py", "unittest.py"])
        self.assertEqual(stdlib_shadow_files(["helper.py"]), [])
        self.assertEqual(stdlib_shadow_files(["sub/unittest.py"]), [])
        self.assertEqual(stdlib_shadow_files(["unittest.txt"]), [])


class TestShadowGate(unittest.TestCase):
    def test_actor_added_unittest_is_rejected(self):
        d = _make_repo()
        (d / "unittest.py").write_text("import sys\nsys.exit(0)\n")
        gate = admit(load(d / "loop.toml"), Git(d), set(), "add", lambda p: False)
        self.assertFalse(gate.ok)
        self.assertTrue(gate.reason.startswith("stdlib_shadow"), gate.reason)
        self.assertIn("unittest.py", gate.reason)

    def test_actor_added_helper_is_admitted(self):
        d = _make_repo()
        (d / "helper.py").write_text("x = 1\n")
        gate = admit(load(d / "loop.toml"), Git(d), set(), "add", lambda p: False)
        self.assertTrue(gate.ok, gate.reason)

    def test_pre_existing_shadow_file_modified_is_not_flagged(self):
        # Only *added* files are gated: a file already committed before the
        # loop started is the repo's own business, not a new shadow.
        d = _make_repo(with_shadow_committed=True)
        (d / "unittest.py").write_text("# edited, was already committed\n")
        gate = admit(load(d / "loop.toml"), Git(d), set(), "add", lambda p: False)
        self.assertTrue(gate.ok, gate.reason)

    def test_check_worktree_reports_shadow_gate(self):
        d = _make_repo()
        (d / "unittest.py").write_text("import sys\nsys.exit(0)\n")
        r = check_worktree(load(d / "loop.toml"), Git(d))
        gates = {g["name"]: g for g in r.admission}
        self.assertIn("stdlib_shadow", gates)
        self.assertFalse(gates["stdlib_shadow"]["ok"])


if __name__ == "__main__":
    unittest.main()
