"""The report's two ways of lying: calling a line covered because nothing measured it, and
calling a line uncovered because the run that measured it was too narrow. The first is caught by
treating an unmeasured file inside the scope as fully uncovered; the second by forcing every
report to name its run, and by keeping files outside the scope out of the gap list."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from diff_coverage import (  # noqa: E402
    as_ranges, changed_lines, measured_roots, missing_lines, render, uncovered, unmeasured,
)

DIFF = """diff --git a/backend/app/x.py b/backend/app/x.py
index 1111111..2222222 100644
--- a/backend/app/x.py
+++ b/backend/app/x.py
@@ -10,6 +10,9 @@ def fee(amount):
     base = amount
-    old = 1
+    if amount < 0:
+        raise ValueError("negative")
+    rate = Decimal("0.3")
     return base
"""


class TheDiff(unittest.TestCase):
    def test_only_the_lines_the_diff_adds_are_counted(self):
        """A deleted line has nothing to cover, and counting it would make every removal look
        like a gap."""
        self.assertEqual(changed_lines(DIFF), {"backend/app/x.py": {11, 12, 13}})

    def test_a_file_the_diff_only_shortens_drops_out(self):
        diff = ("--- a/backend/app/y.py\n+++ b/backend/app/y.py\n"
                "@@ -1,3 +1,2 @@\n line\n-gone\n line\n")
        self.assertEqual(changed_lines(diff), {})


class TheReport(unittest.TestCase):
    def test_coverage_py_shape_is_read(self):
        report = {"files": {"app/x.py": {"missing_lines": [12, 13], "summary": {}}}}
        self.assertEqual(missing_lines(report), {"app/x.py": {12, 13}})

    def test_istanbul_shape_is_read_without_being_told(self):
        """vitest, nyc and jest all write this one; a project should not have to declare which of
        its own files it handed over."""
        report = {"/repo/src/a.ts": {
            "path": "/repo/src/a.ts",
            "statementMap": {"0": {"start": {"line": 4}, "end": {"line": 4}},
                             "1": {"start": {"line": 7}, "end": {"line": 9}}},
            "s": {"0": 3, "1": 0}}}
        self.assertEqual(missing_lines(report, Path("/repo")), {"src/a.ts": {7, 8, 9}})

    def test_a_shape_nobody_recognises_reads_as_nothing_measured(self):
        self.assertEqual(missing_lines({"totals": {"percent": 91.2}}), {})

    def test_the_measured_scope_is_read_from_the_report_itself(self):
        self.assertEqual(measured_roots({"app/x.py": set(), "scripts/y.py": set()}),
                         {"app", "scripts"})


class TheGap(unittest.TestCase):
    def test_the_gap_is_the_intersection_of_changed_and_unexecuted(self):
        """Line 11 is changed and executed; 12-13 are changed and never ran; 40 never ran but
        this branch did not touch it — only 12-13 are this branch's problem."""
        gaps = uncovered({"backend/app/x.py": {11, 12, 13}},
                         {"app/x.py": {12, 13, 40}}, root="backend")
        self.assertEqual(gaps, {"backend/app/x.py": {12, 13}})

    def test_a_changed_file_no_run_imported_counts_as_fully_uncovered(self):
        """The dangerous direction: a file inside the measured scope but absent from the report
        means no test reached it at all, so reading that absence as "nothing missing" would
        report a green line for untested code."""
        gaps = uncovered({"backend/app/new.py": {4, 5}}, {"app/x.py": set()}, root="backend")
        self.assertEqual(gaps, {"backend/app/new.py": {4, 5}})

    def test_a_fully_covered_change_reports_no_gap(self):
        self.assertEqual(uncovered({"backend/app/x.py": {11}}, {"app/x.py": {40}}, root="backend"),
                         {})

    def test_source_outside_the_run_s_scope_is_unmeasured_not_a_gap(self):
        """A run pointed at `app` alone says nothing about `scripts/`. Reporting those lines as
        uncovered would cry wolf on every tooling change, and a reviewer would learn to skip the
        section — the one failure this report cannot afford."""
        changed = {"scripts/tool.py": {10, 11}}
        measured = {"app/x.py": {40}}
        self.assertEqual(uncovered(changed, measured, root="backend"), {})
        self.assertEqual(unmeasured(changed, measured, root="backend"), {"scripts/tool.py": 2})

    def test_the_same_file_is_a_gap_once_the_run_covers_its_directory(self):
        changed = {"scripts/tool.py": {10, 11}}
        measured = {"app/x.py": set(), "scripts/other.py": set()}
        self.assertEqual(uncovered(changed, measured, root=""), {"scripts/tool.py": {10, 11}})
        self.assertEqual(unmeasured(changed, measured, root=""), {})

    def test_a_kind_of_file_no_coverage_tool_reads_is_listed_not_counted(self):
        """Silence about a `.sql` or a `.sh` would read as success."""
        changed = {"migrations/001.sql": {1, 2}, "backend/app/x.py": {11}}
        measured = {"app/x.py": set()}
        self.assertEqual(uncovered(changed, measured, root="backend"), {})
        self.assertEqual(unmeasured(changed, measured, root="backend"), {"migrations/001.sql": 2})

    def test_a_frontend_file_is_measured_like_any_other_source(self):
        changed = {"frontend/src/a.tsx": {4, 5}}
        measured = {"src/a.tsx": {5}}
        self.assertEqual(uncovered(changed, measured, root="frontend"),
                         {"frontend/src/a.tsx": {5}})


class TheSection(unittest.TestCase):
    def test_consecutive_lines_collapse_into_one_range(self):
        self.assertEqual(as_ranges({12, 13, 14, 20, 21, 30}), [(12, 14), (20, 21), (30, 30)])

    def test_the_section_names_the_run_that_produced_it(self):
        """A number read from a targeted run means something different from the same number read
        from the whole suite, so the provenance travels with it."""
        text = render({"backend/app/x.py": {12, 13}}, {"backend/app/x.py": {11, 12, 13}}, {},
                      suite="backend suite, 1842 tests")
        self.assertIn("backend suite, 1842 tests", text)
        self.assertIn("| `backend/app/x.py` | 12-13 |", text)
        self.assertIn("Changed lines measured: 3", text)
        self.assertIn("never executed by a test: 2", text)

    def test_a_clean_section_says_so_instead_of_printing_an_empty_table(self):
        text = render({}, {"backend/app/x.py": {11}}, {}, suite="targeted, 12 tests")
        self.assertIn("No changed line is left uncovered.", text)
        self.assertNotIn("|---|", text)


if __name__ == "__main__":
    unittest.main()
