"""Exercise the actual vendored CLI and rejection paths in a disposable project."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
ADR = ROOT / "scripts/adr"
CHECK = ROOT / "scripts/check_adrs.py"
VALID = """# 1. Keep isolated ownership

Date: 2026-09-13

## Status

Accepted

## Context

Two services need an explicit source of truth.

## Decision

Each service writes only its own database.

## Consequences

Consumers use APIs and must handle unavailable dependencies.
"""


class AdrToolsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="adr-test-")
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)
        self.directory = self.cwd / "docs/adr"
        self.directory.mkdir(parents=True)
        self.record = self.directory / "0001-keep-isolated-ownership.md"
        self.record.write_text(VALID, encoding="utf-8")

    def check(self, expected):
        result = subprocess.run(
            [sys.executable, str(CHECK), str(self.directory)],
            cwd=self.cwd, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_valid_record(self):
        self.assertIn("OK: 1 ADRs", self.check(0))

    def test_empty_directory_rejected(self):
        self.record.unlink()
        self.assertIn("no numbered ADRs", self.check(1))

    def test_missing_decision_rejected(self):
        self.record.write_text(VALID.replace("## Decision", "## Notes"), encoding="utf-8")
        self.assertIn("missing or empty section Decision", self.check(1))

    def test_broken_link_rejected(self):
        self.record.write_text(VALID + "\n[Next](0002-missing.md)\n", encoding="utf-8")
        self.assertIn("broken local link", self.check(1))

    def test_duplicate_number_rejected(self):
        (self.directory / "0001-another-decision.md").write_text(VALID, encoding="utf-8")
        self.assertIn("duplicate ADR number", self.check(1))

    def test_invalid_date_rejected(self):
        self.record.write_text(VALID.replace("2026-09-13", "2026-02-30"), encoding="utf-8")
        self.assertIn("valid Date", self.check(1))

    def test_upstream_init_new_list_and_unfinished_record(self):
        self.record.unlink()
        subprocess.run([str(ADR), "init", "docs/adr"], cwd=self.cwd, check=True, capture_output=True)
        created = subprocess.run(
            [str(ADR), "new", "Use explicit ownership"],
            cwd=self.cwd, check=True, capture_output=True, text=True,
            env={**os.environ, "VISUAL": "true", "EDITOR": "true"},
        )
        self.assertEqual(created.stdout.strip(), "docs/adr/0002-use-explicit-ownership.md")
        listed = subprocess.run([str(ADR), "list"], cwd=self.cwd, check=True, capture_output=True, text=True)
        self.assertEqual(len(listed.stdout.splitlines()), 2)
        self.assertIn("0002-use-explicit-ownership.md", listed.stdout)
        self.assertIn("unfinished template text", self.check(1))


if __name__ == "__main__":
    unittest.main()
