"""Tests for .non/webpbn import: nonogram_webpbn.py.

The fixture text below is a small original puzzle (a 5x5 diamond) I
wrote myself, formatted exactly the way real .non files from webpbn.com's
published archive are structured (checked against several real samples
while building the parser) - not a copy of anyone else's copyrighted
puzzle content.
"""

import tempfile
import unittest
from pathlib import Path

from nonogram_tool.nonogram_overlap import FILLED, GAP, UNKNOWN
from nonogram_tool.nonogram_webpbn import parse_non, load_non


DIAMOND_NON = """\
catalogue "test archive #1"
title "Diamond"
by "Test Author"
copyright "&copy; 2024 by Test Author"
license CC-BY-3.0
width 5
height 5

rows
1
3
5
3
1

columns
1
3
5
3
1

goal "0010001110111110111000100"
"""

DIAMOND_ROWS = [[1], [3], [5], [3], [1]]
DIAMOND_COLS = [[1], [3], [5], [3], [1]]


class TestParseNonHappyPath(unittest.TestCase):
    def test_parses_clues_and_dimensions(self):
        puzzle, metadata, errors = parse_non(DIAMOND_NON)
        self.assertEqual(errors, [])
        self.assertEqual(puzzle.width, 5)
        self.assertEqual(puzzle.height, 5)
        self.assertEqual(puzzle.row_clues, DIAMOND_ROWS)
        self.assertEqual(puzzle.col_clues, DIAMOND_COLS)

    def test_metadata_fields_extracted_and_html_unescaped(self):
        _, metadata, errors = parse_non(DIAMOND_NON)
        self.assertEqual(errors, [])
        self.assertEqual(metadata["catalogue"], "test archive #1")
        self.assertEqual(metadata["title"], "Diamond")
        self.assertEqual(metadata["by"], "Test Author")
        self.assertEqual(metadata["copyright"], "© 2024 by Test Author")  # &copy; -> ©
        self.assertEqual(metadata["license"], "CC-BY-3.0")

    def test_parsed_clues_actually_solve_to_the_intended_shape(self):
        # Not just "it parsed" - the clues genuinely describe a diamond,
        # solvable by this tool's own propagation.
        puzzle, _, errors = parse_non(DIAMOND_NON)
        self.assertEqual(errors, [])
        seeds = [(r, 1) for r in range(1, puzzle.height + 1)] + [
            (1, c) for c in range(1, puzzle.width + 1)
        ]
        puzzle.propagate(seeds)
        self.assertTrue(puzzle.is_solved())
        self.assertEqual(puzzle.get_row(1), [GAP, GAP, FILLED, GAP, GAP])
        self.assertEqual(puzzle.get_row(3), [FILLED] * 5)

    def test_blank_row_zero_becomes_empty_clue_list(self):
        text = (
            'width 3\nheight 2\n\nrows\n0\n1\n\ncolumns\n1\n0\n1\n'
        )
        puzzle, _, errors = parse_non(text)
        self.assertEqual(errors, [])
        self.assertEqual(puzzle.row_clues, [[], [1]])
        self.assertEqual(puzzle.col_clues, [[1], [], [1]])

    def test_goal_line_is_ignored_without_error(self):
        # DIAMOND_NON already includes a goal line; this asserts its
        # presence specifically isn't what makes that fixture parse.
        text = DIAMOND_NON.replace('goal "0010001110111110111000100"\n', "")
        puzzle, _, errors = parse_non(text)
        self.assertEqual(errors, [])
        self.assertEqual(puzzle.row_clues, DIAMOND_ROWS)

    def test_metadata_is_empty_when_no_header_keys_present(self):
        text = "width 1\nheight 1\n\nrows\n1\n\ncolumns\n1\n"
        puzzle, metadata, errors = parse_non(text)
        self.assertEqual(errors, [])
        self.assertEqual(metadata, {})

    def test_unrecognized_line_outside_any_section_is_ignored(self):
        # The .non spec says parsers must ignore lines they don't
        # recognize - unlike this repo's own stricter native format.
        text = "width 1\nheight 1\nsomeFutureKey 42\n\nrows\n1\n\ncolumns\n1\n"
        puzzle, _, errors = parse_non(text)
        self.assertEqual(errors, [])
        self.assertEqual(puzzle.row_clues, [[1]])


class TestParseNonErrors(unittest.TestCase):
    def test_missing_width_and_height_both_reported(self):
        _, _, errors = parse_non("rows\n1\n\ncolumns\n1\n")
        labels = [label for label, _ in errors]
        self.assertIn("width", labels)
        self.assertIn("height", labels)

    def test_row_count_mismatch_errors(self):
        text = "width 1\nheight 3\n\nrows\n1\n1\n\ncolumns\n1\n"
        puzzle, _, errors = parse_non(text)
        self.assertIsNone(puzzle)
        self.assertTrue(any("row" in label for label, _ in errors))

    def test_column_count_mismatch_errors(self):
        text = "width 2\nheight 1\n\nrows\n1\n\ncolumns\n1\n"
        puzzle, _, errors = parse_non(text)
        self.assertIsNone(puzzle)
        self.assertTrue(any("column" in label for label, _ in errors))

    def test_invalid_width_errors(self):
        text = "width abc\nheight 1\n\nrows\n1\n\ncolumns\n1\n"
        puzzle, _, errors = parse_non(text)
        self.assertIsNone(puzzle)
        self.assertTrue(any("Invalid width" in msg for _, msg in errors))

    def test_unparseable_clue_line_errors(self):
        text = "width 1\nheight 1\n\nrows\nnot-a-clue\n\ncolumns\n1\n"
        puzzle, _, errors = parse_non(text)
        self.assertIsNone(puzzle)
        self.assertTrue(errors)

    def test_metadata_key_without_quotes_errors(self):
        text = 'title Unquoted\nwidth 1\nheight 1\n\nrows\n1\n\ncolumns\n1\n'
        puzzle, _, errors = parse_non(text)
        self.assertIsNone(puzzle)
        self.assertTrue(any("title" in msg for _, msg in errors))


class TestColorRejection(unittest.TestCase):
    def test_color_section_key_is_rejected(self):
        text = (
            'width 1\nheight 1\n\ncolor black #000000\n\n'
            "rows\n1\n\ncolumns\n1\n"
        )
        puzzle, metadata, errors = parse_non(text)
        self.assertIsNone(puzzle)
        self.assertEqual(len(errors), 1)
        self.assertIn("multi-color", errors[0][1])

    def test_colored_run_token_is_rejected_even_without_a_color_key(self):
        text = "width 4\nheight 1\n\nrows\n3a\n\ncolumns\n1\n1\n1\n1\n"
        puzzle, metadata, errors = parse_non(text)
        self.assertIsNone(puzzle)
        self.assertIn("multi-color", errors[0][1])

    def test_rejection_happens_before_other_structural_errors(self):
        # Even a file that's missing width/height entirely should report
        # the color rejection, not "no width declared" - the color
        # scope decision applies before anything else is checked.
        text = "color a #ff0000\nrows\n3a\n"
        puzzle, metadata, errors = parse_non(text)
        self.assertIsNone(puzzle)
        self.assertEqual(len(errors), 1)
        self.assertIn("multi-color", errors[0][1])

    def test_plain_monochrome_puzzle_is_not_flagged_as_colored(self):
        puzzle, _, errors = parse_non(DIAMOND_NON)
        self.assertIsNotNone(puzzle)
        self.assertEqual(errors, [])


class TestLoadNon(unittest.TestCase):
    def test_loads_from_a_real_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "diamond.non"
            path.write_text(DIAMOND_NON, encoding="utf-8")
            puzzle, metadata, errors = load_non(path)
        self.assertEqual(errors, [])
        self.assertEqual(puzzle.row_clues, DIAMOND_ROWS)
        self.assertEqual(metadata["title"], "Diamond")


if __name__ == "__main__":
    unittest.main()
