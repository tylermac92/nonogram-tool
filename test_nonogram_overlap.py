#!/usr/bin/env python3
"""
Test suite for nonogram_overlap.py

Run with:
    python3 -m unittest test_nonogram_overlap.py -v

No third-party dependencies - built entirely on the standard library, so it
runs anywhere Python 3 does.

Design note: the three worked examples from the cheatsheet are pinned at the
*numeric result* level (S, G, minLen, slack, block starts, guaranteed
ranges) - not as full-text snapshots of format_report()'s output. That's
deliberate: a cosmetic formatting tweak (spacing, wording, column widths)
shouldn't break these tests, but a wrong number anywhere in the math should.
format_report() itself is checked for a handful of key substrings and
structural properties instead of an exact multi-line match, for the same
reason.
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nonogram_overlap import (  # noqa: E402
    LineError,
    analyze,
    batch_fill_summary,
    batch_sort_key,
    build_table,
    colorize,
    format_batch_report,
    format_report,
    parse_batch,
    parse_clues,
    render_line,
    ruler,
    section,
)

SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nonogram_overlap.py")


# ---------------------------------------------------------------------------
# parse_clues
# ---------------------------------------------------------------------------
class TestParseClues(unittest.TestCase):
    def test_comma_separated(self):
        self.assertEqual(parse_clues("19,5,53"), [19, 5, 53])

    def test_space_separated(self):
        self.assertEqual(parse_clues("19 5 53"), [19, 5, 53])

    def test_mixed_separators_and_whitespace(self):
        self.assertEqual(parse_clues(" 19,  5 ,53 "), [19, 5, 53])

    def test_single_zero_means_blank_line(self):
        self.assertEqual(parse_clues("0"), [])

    def test_zero_combined_with_other_clues_rejected(self):
        with self.assertRaises(LineError):
            parse_clues("0,5")

    def test_negative_clue_rejected(self):
        with self.assertRaises(LineError):
            parse_clues("-3,5")

    def test_non_integer_token_rejected(self):
        with self.assertRaises(LineError):
            parse_clues("abc")

    def test_empty_string_rejected(self):
        with self.assertRaises(LineError):
            parse_clues("")

    def test_whitespace_only_rejected(self):
        with self.assertRaises(LineError):
            parse_clues("   ")


# ---------------------------------------------------------------------------
# analyze - the three worked examples, pinned
# ---------------------------------------------------------------------------
class TestAnalyzeWorkedExamples(unittest.TestCase):
    """These three cases were worked by hand earlier and cross-checked
    against the script's output. If any of these numbers change, something
    in the core math broke."""

    def test_row_19_5_53(self):
        r = analyze(80, [19, 5, 53])
        self.assertEqual(r["sum"], 77)
        self.assertEqual(r["gaps"], 2)
        self.assertEqual(r["min_len"], 79)
        self.assertEqual(r["slack"], 1)

        b1, b2, b3 = r["blocks"]
        self.assertEqual((b1["start"], b1["left_end"]), (1, 19))
        self.assertEqual((b1["g_start"], b1["g_end"], b1["g_count"]), (2, 19, 18))

        self.assertEqual((b2["start"], b2["left_end"]), (21, 25))
        self.assertEqual((b2["g_start"], b2["g_end"], b2["g_count"]), (22, 25, 4))

        self.assertEqual((b3["start"], b3["left_end"]), (27, 79))
        self.assertEqual((b3["g_start"], b3["g_end"], b3["g_count"]), (28, 79, 52))

        self.assertEqual(r["total_guaranteed"], 74)

    def test_row_5_2_27_6_11(self):
        r = analyze(80, [5, 2, 27, 6, 11])
        self.assertEqual(r["sum"], 51)
        self.assertEqual(r["gaps"], 4)
        self.assertEqual(r["min_len"], 55)
        self.assertEqual(r["slack"], 25)

        starts = [(b["start"], b["left_end"]) for b in r["blocks"]]
        self.assertEqual(starts, [(1, 5), (7, 8), (10, 36), (38, 43), (45, 55)])

        # Only the block of size 27 exceeds the slack of 25.
        g_counts = [b["g_count"] for b in r["blocks"]]
        self.assertEqual(g_counts, [0, 0, 2, 0, 0])

        block3 = r["blocks"][2]
        self.assertEqual((block3["g_start"], block3["g_end"]), (35, 36))
        self.assertEqual(r["total_guaranteed"], 2)

    def test_column_46_6_17(self):
        r = analyze(80, [46, 6, 17])
        self.assertEqual(r["sum"], 69)
        self.assertEqual(r["gaps"], 2)
        self.assertEqual(r["min_len"], 71)
        self.assertEqual(r["slack"], 9)

        b1, b2, b3 = r["blocks"]
        self.assertEqual((b1["g_start"], b1["g_end"], b1["g_count"]), (10, 46, 37))
        self.assertEqual((b2["g_start"], b2["g_end"], b2["g_count"]), (None, None, 0))
        self.assertEqual((b3["g_start"], b3["g_end"], b3["g_count"]), (64, 71, 8))

        self.assertEqual(r["total_guaranteed"], 45)


# ---------------------------------------------------------------------------
# analyze - edge cases
# ---------------------------------------------------------------------------
class TestAnalyzeEdgeCases(unittest.TestCase):
    def test_slack_zero_is_fully_determined(self):
        r = analyze(10, [4, 5])
        self.assertEqual(r["slack"], 0)
        b1, b2 = r["blocks"]
        self.assertEqual((b1["g_start"], b1["g_end"], b1["g_count"]), (1, 4, 4))
        self.assertEqual((b2["g_start"], b2["g_end"], b2["g_count"]), (6, 10, 5))
        self.assertEqual(r["total_guaranteed"], 9)

    def test_blank_line(self):
        r = analyze(15, [])
        self.assertTrue(r["is_blank"])
        self.assertEqual(r["blocks"], [])
        self.assertEqual(r["total_guaranteed"], 0)
        self.assertEqual(r["slack"], 15)

    def test_clues_dont_fit_raises(self):
        # 8 + 5 + 1 gap = 14, but the line is only 10 long.
        with self.assertRaises(LineError):
            analyze(10, [8, 5])

    def test_nonpositive_length_raises(self):
        with self.assertRaises(LineError):
            analyze(0, [1])
        with self.assertRaises(LineError):
            analyze(-5, [1])

    def test_no_guaranteed_cells_when_slack_is_large(self):
        r = analyze(20, [2, 3])
        self.assertEqual(r["total_guaranteed"], 0)
        self.assertTrue(all(b["g_start"] is None for b in r["blocks"]))

    def test_single_block_exactly_fills_line(self):
        # A single block equal to the full line length: slack 0, one block.
        r = analyze(10, [10])
        self.assertEqual(r["slack"], 0)
        self.assertEqual(r["total_guaranteed"], 10)


# ---------------------------------------------------------------------------
# Formatting helpers: build_table, section, ruler, render_line, colorize
# ---------------------------------------------------------------------------
class TestBuildTable(unittest.TestCase):
    def test_header_divider_and_rows_all_same_length(self):
        headers = ["#", "size", "start", "leftmost", "count", "guaranteed"]
        rows = [
            ["1", "19", "1", "1-19", "18", "2-19"],
            ["2", "5", "21", "21-25", "4", "22-25"],
            ["3", "53", "27", "27-79", "52", "28-79"],
        ]
        lines = build_table(headers, rows)
        header_line, divider, *data_rows = lines
        self.assertEqual(len(divider), len(header_line))
        for row in data_rows:
            self.assertEqual(len(row), len(header_line))
        self.assertEqual(set(divider.strip()), {"-"})

    def test_columns_expand_for_wider_values(self):
        # Regression test for the original bug: a hardcoded divider length
        # went out of sync with the header once values got wider.
        headers = ["#", "size", "start", "leftmost", "count", "guaranteed"]
        rows = [["1", "150", "1", "1-150", "142", "9-150"]]
        lines = build_table(headers, rows)
        header_line, divider, data_row = lines
        self.assertEqual(len(divider), len(header_line))
        self.assertEqual(len(data_row), len(header_line))
        self.assertIn("1-150", data_row)


class TestSection(unittest.TestCase):
    def test_divider_matches_title_width(self):
        title_line, divider = section("STEP 1 - Slack")
        self.assertEqual(len(divider), len(title_line))
        self.assertEqual(set(divider), {"-"})


class TestRuler(unittest.TestCase):
    def test_ruler_20(self):
        self.assertEqual(ruler(20), "      5   10   15   20")

    def test_ruler_10(self):
        self.assertEqual(ruler(10), "      5   10")

    def test_ruler_length_matches_prefix_plus_length(self):
        self.assertEqual(len(ruler(37)), 37 + 2)


class TestRenderLine(unittest.TestCase):
    def test_row_19_5_53(self):
        r = analyze(80, [19, 5, 53])
        self.assertEqual(
            render_line(r),
            "  .##################..####..####################################################.",
        )

    def test_slack_zero_marks_forced_gap(self):
        r = analyze(10, [4, 5])
        self.assertEqual(render_line(r), "  ####x#####")


class TestColorize(unittest.TestCase):
    def test_disabled_returns_input_unchanged(self):
        self.assertEqual(colorize("##..xx", False), "##..xx")

    def test_enabled_wraps_each_run_once(self):
        result = colorize("##..xx", True)
        # 3 runs (##, .., xx) -> exactly 3 reset codes, not one per character.
        self.assertEqual(result.count("\033[0m"), 3)
        self.assertIn("\033[1;32m##\033[0m", result)
        self.assertIn("\033[2m..\033[0m", result)
        self.assertIn("\033[31mxx\033[0m", result)

    def test_unmapped_characters_pass_through_uncolored(self):
        result = colorize("  ##", True)
        self.assertTrue(result.startswith("  "))  # leading spaces untouched
        self.assertIn("\033[1;32m##\033[0m", result)


# ---------------------------------------------------------------------------
# format_report - structural/substring checks, not full-text snapshots
# ---------------------------------------------------------------------------
class TestFormatReport(unittest.TestCase):
    def test_no_color_has_no_ansi_codes(self):
        r = analyze(80, [19, 5, 53])
        report = format_report(r, use_color=False)
        self.assertNotIn("\033[", report)

    def test_color_enabled_has_ansi_codes(self):
        r = analyze(80, [19, 5, 53])
        report = format_report(r, use_color=True)
        self.assertIn("\033[", report)

    def test_default_use_color_is_false(self):
        r = analyze(80, [19, 5, 53])
        self.assertEqual(format_report(r), format_report(r, use_color=False))

    def test_summary_lists_correct_fill_ranges(self):
        r = analyze(80, [19, 5, 53])
        report = format_report(r)
        self.assertIn("Fill cells: 2-19, 22-25, 28-79", report)
        self.assertIn("74 of 80", report)

    def test_blank_line_section_present(self):
        r = analyze(15, [])
        report = format_report(r)
        self.assertIn("BLANK LINE", report)
        self.assertIn("All 15 cells are guaranteed empty", report)

    def test_slack_zero_reports_fully_determined(self):
        r = analyze(10, [4, 5])
        report = format_report(r)
        self.assertIn("fully determined", report)


# ---------------------------------------------------------------------------
# Batch mode: parsing
# ---------------------------------------------------------------------------
class TestParseBatch(unittest.TestCase):
    def test_basic_rows_and_columns(self):
        text = """
        SIZE: 80
        ROWS
        1: 19,5,53
        2: 5,2,27,6,11
        COLUMNS
        1: 46,6,17
        """
        entries, errors = parse_batch(text)
        self.assertEqual(errors, [])
        self.assertEqual(len(entries), 3)

        by_label = {e["label"]: e for e in entries}
        self.assertEqual(by_label["Row 1"]["length"], 80)
        self.assertEqual(by_label["Row 1"]["result"]["slack"], 1)
        self.assertEqual(by_label["Column 1"]["result"]["slack"], 9)

    def test_size_square_shorthand(self):
        entries, errors = parse_batch("SIZE: 20\nROWS\n1: 5,3\n")
        self.assertEqual(errors, [])
        self.assertEqual(entries[0]["length"], 20)

    def test_size_rectangular_wxh_maps_rows_to_width_columns_to_height(self):
        text = "SIZE: 15x10\nROWS\n1: 15\nCOLUMNS\n1: 10\n"
        entries, errors = parse_batch(text)
        self.assertEqual(errors, [])
        by_label = {e["label"]: e for e in entries}
        self.assertEqual(by_label["Row 1"]["length"], 15)
        self.assertEqual(by_label["Column 1"]["length"], 10)

    def test_blank_line_clue_zero(self):
        entries, errors = parse_batch("SIZE: 15\nROWS\n1: 0\n")
        self.assertEqual(errors, [])
        self.assertTrue(entries[0]["result"]["is_blank"])

    def test_comments_and_blank_lines_ignored(self):
        text = "# a comment\nSIZE: 10\n\nROWS\n# another comment\n1: 5\n"
        entries, errors = parse_batch(text)
        self.assertEqual(errors, [])
        self.assertEqual(len(entries), 1)

    def test_clue_line_before_any_section_is_an_error(self):
        entries, errors = parse_batch("SIZE: 10\n1: 5\n")
        self.assertEqual(entries, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("before a ROWS or COLUMNS", errors[0][1])

    def test_missing_size_is_an_error_per_line(self):
        entries, errors = parse_batch("ROWS\n1: 5,3\n")
        self.assertEqual(entries, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("No SIZE declared", errors[0][1])

    def test_invalid_size_is_an_error(self):
        entries, errors = parse_batch("SIZE: abc\nROWS\n1: 5\n")
        labels_and_messages = [msg for _, msg in errors]
        self.assertTrue(any("Invalid SIZE" in m for m in labels_and_messages))

    def test_unparseable_line_is_an_error_not_a_crash(self):
        entries, errors = parse_batch("SIZE: 10\nROWS\nnot a valid line\n")
        self.assertEqual(entries, [])
        self.assertEqual(len(errors), 1)

    def test_clues_dont_fit_is_a_per_line_error(self):
        entries, errors = parse_batch("SIZE: 10\nROWS\n1: 8,5\n")
        self.assertEqual(entries, [])
        self.assertIn("don't fit", errors[0][1])

    def test_bad_line_does_not_abort_the_rest_of_the_batch(self):
        text = "SIZE: 80\nROWS\n1: 19,5,53\n2: abc\n3: 46,6,17\n"
        entries, errors = parse_batch(text)
        self.assertEqual(len(entries), 2)
        self.assertEqual(len(errors), 1)
        self.assertEqual({e["label"] for e in entries}, {"Row 1", "Row 3"})

    def test_empty_input_produces_nothing(self):
        entries, errors = parse_batch("")
        self.assertEqual(entries, [])
        self.assertEqual(errors, [])


# ---------------------------------------------------------------------------
# Batch mode: sorting and summary
# ---------------------------------------------------------------------------
class TestBatchSortAndSummary(unittest.TestCase):
    def setUp(self):
        text = (
            "SIZE: 80\n"
            "ROWS\n"
            "1: 19,5,53\n"       # slack 1
            "2: 5,2,27,6,11\n"   # slack 25
            "3: 0\n"             # blank -> fully determined
            "COLUMNS\n"
            "1: 46,6,17\n"       # slack 9
        )
        self.entries, self.errors = parse_batch(text)
        self.assertEqual(self.errors, [])

    def test_sorted_order_is_fully_determined_first_then_ascending_slack(self):
        ordered = sorted(self.entries, key=batch_sort_key)
        self.assertEqual(
            [e["label"] for e in ordered],
            ["Row 3", "Row 1", "Column 1", "Row 2"],
        )

    def test_fill_summary_for_blank_line(self):
        blank_entry = next(e for e in self.entries if e["label"] == "Row 3")
        fill_text, resolved, pct = batch_fill_summary(blank_entry)
        self.assertEqual(fill_text, "ALL EMPTY")
        self.assertEqual(resolved, 80)
        self.assertEqual(pct, 100.0)

    def test_fill_summary_for_partial_line(self):
        row1 = next(e for e in self.entries if e["label"] == "Row 1")
        fill_text, resolved, pct = batch_fill_summary(row1)
        self.assertEqual(fill_text, "2-19, 22-25, 28-79")
        self.assertEqual(resolved, 74)
        self.assertAlmostEqual(pct, 92.5)

    def test_fill_summary_for_slack_zero_line(self):
        entries, _ = parse_batch("SIZE: 10\nROWS\n1: 4,5\n")
        fill_text, resolved, pct = batch_fill_summary(entries[0])
        self.assertEqual(fill_text, "ALL (fully determined)")
        self.assertEqual(resolved, 10)
        self.assertEqual(pct, 100.0)


# ---------------------------------------------------------------------------
# Batch mode: report formatting
# ---------------------------------------------------------------------------
class TestFormatBatchReport(unittest.TestCase):
    def test_report_contains_sorted_rows_and_totals(self):
        entries, errors = parse_batch(
            "SIZE: 80\nROWS\n1: 19,5,53\n2: 5,2,27,6,11\nCOLUMNS\n1: 46,6,17\n"
        )
        report = format_batch_report(entries, errors)
        self.assertIn("2-19, 22-25, 28-79", report)
        self.assertIn("35-36", report)
        self.assertIn("10-46, 64-71", report)
        # Row 1 (slack 1) must appear before Row 2 (slack 25).
        self.assertLess(report.index("Row 1"), report.index("Row 2"))

    def test_errors_section_present_when_there_are_errors(self):
        entries, errors = parse_batch("SIZE: 80\nROWS\n1: 8,90\n")
        report = format_batch_report(entries, errors)
        self.assertIn("ERRORS (1)", report)

    def test_no_errors_section_when_there_are_no_errors(self):
        entries, errors = parse_batch("SIZE: 80\nROWS\n1: 19,5,53\n")
        report = format_batch_report(entries, errors)
        self.assertNotIn("ERRORS", report)

    def test_full_detail_flag_adds_per_line_reports(self):
        entries, errors = parse_batch("SIZE: 80\nROWS\n1: 19,5,53\n")
        short_report = format_batch_report(entries, errors, show_full=False)
        long_report = format_batch_report(entries, errors, show_full=True)
        self.assertGreater(len(long_report), len(short_report))
        self.assertIn("STEPS 2 & 3", long_report)
        self.assertNotIn("STEPS 2 & 3", short_report)

    def test_no_color_has_no_ansi_codes(self):
        entries, errors = parse_batch("SIZE: 80\nROWS\n1: 0\n")
        report = format_batch_report(entries, errors, use_color=False)
        self.assertNotIn("\033[", report)

    def test_color_highlights_fully_determined_rows(self):
        entries, errors = parse_batch("SIZE: 80\nROWS\n1: 0\n")
        report = format_batch_report(entries, errors, use_color=True)
        self.assertIn("\033[", report)

    def test_column_alignment_preserved_with_color_on(self):
        # Coloring is applied to whole rows after formatting, so it must
        # never change the *visible* column widths - strip ANSI codes back
        # out and compare against the uncolored version.
        import re as _re

        entries, errors = parse_batch(
            "SIZE: 80\nROWS\n1: 19,5,53\n2: 0\nCOLUMNS\n1: 46,6,17\n"
        )
        plain = format_batch_report(entries, errors, use_color=False)
        colored = format_batch_report(entries, errors, use_color=True)
        stripped = _re.sub(r"\033\[[0-9;]*m", "", colored)
        self.assertEqual(plain, stripped)


# ---------------------------------------------------------------------------
# CLI smoke tests - exercise main()/argv parsing end to end via subprocess
# ---------------------------------------------------------------------------
class TestCLI(unittest.TestCase):
    def run_cli(self, args, stdin_text=None):
        return subprocess.run(
            [sys.executable, SCRIPT_PATH, *args],
            input=stdin_text,
            capture_output=True,
            text=True,
            env={**os.environ, "NO_COLOR": "1"},
        )

    def test_single_shot_success(self):
        proc = self.run_cli(["80", "19,5,53"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Fill cells: 2-19, 22-25, 28-79", proc.stdout)

    def test_single_shot_space_separated_clues(self):
        proc = self.run_cli(["80", "19 5 53"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Fill cells: 2-19, 22-25, 28-79", proc.stdout)

    def test_clues_dont_fit_exits_nonzero(self):
        proc = self.run_cli(["10", "8,5"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("don't fit", proc.stderr)

    def test_missing_clues_arg_exits_nonzero(self):
        proc = self.run_cli(["80"])
        self.assertEqual(proc.returncode, 1)

    def test_repl_processes_multiple_lines_then_quits(self):
        proc = self.run_cli([], stdin_text="80\n19,5,53\n80\n0\nq\n")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Fill cells: 2-19, 22-25, 28-79", proc.stdout)
        self.assertIn("BLANK LINE", proc.stdout)

    def test_repl_recovers_from_bad_input(self):
        proc = self.run_cli([], stdin_text="abc\n80\n19,5,53\nq\n")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("not a valid line length", proc.stderr)
        self.assertIn("Fill cells: 2-19, 22-25, 28-79", proc.stdout)

    def test_repl_quits_on_eof(self):
        proc = self.run_cli([], stdin_text="80\n")
        self.assertEqual(proc.returncode, 0)

    # --- batch mode ---------------------------------------------------
    def test_batch_from_stdin(self):
        text = "SIZE: 80\nROWS\n1: 19,5,53\n2: 5,2,27,6,11\nCOLUMNS\n1: 46,6,17\n"
        proc = self.run_cli(["--batch"], stdin_text=text)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("BATCH TRIAGE", proc.stdout)
        self.assertIn("2-19, 22-25, 28-79", proc.stdout)
        self.assertLess(proc.stdout.index("Row 1"), proc.stdout.index("Row 2"))

    def test_batch_from_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as fh:
            fh.write("SIZE: 80\nROWS\n1: 19,5,53\nCOLUMNS\n1: 46,6,17\n")
            path = fh.name
        try:
            proc = self.run_cli(["--batch", path])
            self.assertEqual(proc.returncode, 0)
            self.assertIn("10-46, 64-71", proc.stdout)
        finally:
            os.unlink(path)

    def test_batch_missing_file_exits_nonzero(self):
        proc = self.run_cli(["--batch", "/no/such/file.txt"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Error reading", proc.stderr)

    def test_batch_full_flag(self):
        text = "SIZE: 80\nROWS\n1: 19,5,53\n"
        proc = self.run_cli(["--batch", "--full"], stdin_text=text)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("FULL DETAIL", proc.stdout)
        self.assertIn("STEPS 2 & 3", proc.stdout)

    def test_batch_empty_input_exits_nonzero(self):
        proc = self.run_cli(["--batch"], stdin_text="")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no rows or columns", proc.stderr)

    def test_batch_all_errors_exits_nonzero_but_reports(self):
        proc = self.run_cli(["--batch"], stdin_text="SIZE: 10\nROWS\n1: 8,5\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("ERRORS (1)", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
