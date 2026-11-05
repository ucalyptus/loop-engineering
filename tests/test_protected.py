"""Tests for the protected-files admission gate (Gap 1)."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from loopctl.controller import Git, admit, check_worktree, protected_match, protected_patterns
from loopctl.manifest import Manifest, load

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def _git(cwd, *args, env=None):
    import os
    full = {**os.environ, **GIT_ENV, **(env or {})}
    subprocess.run(["git", *args], cwd=cwd, check=True, env=full,
                   capture_output=True, text=True)


def _make_repo():
    tmp = Path(tempfile.mkdtemp(prefix="loopctl-protected-"))
    (tmp / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (tmp / "test_calc.py").write_text(
        "import unittest, calc\n"
        "class T(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(calc.add(2, 3), 5)\n")
    (tmp / "loop.toml").write_text(
        'name = "calc"\n'
        'goal = "calc works"\n'
        'workdir = "."\n'
        'actor = "true"\n'
        'protected = ["test_calc.py"]\n'
        '[[checks]]\n'
        'name = "add"\n'
        'run = "python3 -m unittest -q test_calc"\n')
    _git(tmp, "init", "-q")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-qm", "initial")
    return tmp


class TestProtectedMatch(unittest.TestCase):
    def test_exact_and_glob_and_suffix(self):
        self.assertTrue(protected_match("test_calc.py", ["test_calc.py"]))
        self.assertTrue(protected_match("test_calc.py", ["test_*.py"]))
        self.assertTrue(protected_match("tests/test_calc.py", ["test_*.py"]))
        self.assertTrue(protected_match("loop.toml", ["*.toml"]))
        self.assertFalse(protected_match("calc.py", ["test_calc.py"]))
        self.assertFalse(protected_match("calc.py", ["test_*.py"]))


class TestProtectedGate(unittest.TestCase):
    def setUp(self):
        self.dir = _make_repo()
        self.m = load(self.dir / "loop.toml")

    def test_manifest_itself_is_always_protected(self):
        self.assertIn("loop.toml", protected_patterns(self.m))
        self.assertIn("test_calc.py", protected_patterns(self.m))

    def test_non_protected_change_is_admitted(self):
        (self.dir / "calc.py").write_text("def add(a, b):\n    return a + b\n")
        gate = admit(self.m, Git(self.dir), set(), "add", lambda p: False)
        self.assertTrue(gate.ok, gate.reason)

    def test_protected_change_is_rejected(self):
        (self.dir / "test_calc.py").write_text("# tampered\n")
        gate = admit(self.m, Git(self.dir), set(), "add", lambda p: False)
        self.assertFalse(gate.ok)
        self.assertTrue(gate.reason.startswith("protected_changed"), gate.reason)
        self.assertIn("test_calc.py", gate.reason)

    def test_manifest_change_is_rejected(self):
        (self.dir / "loop.toml").write_text('name = "calc"\ngoal = "moved"\n')
        gate = admit(self.m, Git(self.dir), set(), "add", lambda p: False)
        self.assertFalse(gate.ok)
        self.assertIn("loop.toml", gate.reason)

    def test_protected_creation_is_rejected(self):
        # A protected pattern that names a not-yet-existing file: creating
        # it is a change to a protected path, and must be rejected too.
        m2 = Manifest(**{**self.m.__dict__, "protected": ("secret.py",)})
        (self.dir / "secret.py").write_text("x = 1\n")
        gate = admit(m2, Git(self.dir), set(), "add", lambda p: False)
        self.assertFalse(gate.ok)
        self.assertIn("secret.py", gate.reason)

    def test_check_worktree_reports_protected_gate(self):
        (self.dir / "test_calc.py").write_text("# tampered\n")
        r = check_worktree(self.m, Git(self.dir))
        gates = {g["name"]: g for g in r.admission}
        self.assertIn("protected", gates)
        self.assertFalse(gates["protected"]["ok"])


if __name__ == "__main__":
    unittest.main()
