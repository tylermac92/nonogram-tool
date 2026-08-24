"""Tests for grid state, wiring, persistence, and undo/redo: nonogram_puzzle.py."""

import tempfile
import unittest
from pathlib import Path

from nonogram_overlap import FILLED, GAP, UNKNOWN
from nonogram_linesolve import LineContradiction
from nonogram_puzzle import Puzzle, line_matches_clue, parse_puzzle, save_puzzle, load_puzzle


class TestConstruction(unittest.TestCase):
    def test_clue_zero_list_normalizes_to_empty_list(self):
        puzzle = Puzzle(row_clues=[[0]], col_clues=[[0]] * 3)
        self.assertEqual(puzzle.row_clues, [[]])
        self.assertEqual(puzzle.col_clues, [[], [], []])

    def test_blank_puzzle_starts_all_unknown(self):
        puzzle = Puzzle(row_clues=[[2]], col_clues=[[1], [1]])
        self.assertEqual(puzzle.get_row(1), [UNKNOWN, UNKNOWN])


class TestAccessors(unittest.TestCase):
    def test_get_row_returns_a_copy(self):
        puzzle = Puzzle(row_clues=[[2]], col_clues=[[1], [1]])
        row = puzzle.get_row(1)
        row[0] = FILLED
        self.assertEqual(puzzle.get_cell(1, 1), UNKNOWN)

    def test_get_col_matches_set_cell(self):
        puzzle = Puzzle(row_clues=[[1], [1]], col_clues=[[1], [1]])
        puzzle.set_cell(2, 1, FILLED)
        self.assertEqual(puzzle.get_col(1), [UNKNOWN, FILLED])

    def test_out_of_range_raises(self):
        puzzle = Puzzle(row_clues=[[1], [1]], col_clues=[[1], [1]])
        for row, col in [(0, 1), (3, 1), (1, 0), (1, 3)]:
            with self.subTest(row=row, col=col):
                with self.assertRaises(ValueError):
                    puzzle.get_cell(row, col)

    def test_set_cell_invalid_state_raises(self):
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        with self.assertRaises(ValueError):
            puzzle.set_cell(1, 1, "?")


class TestLineMatchesClueAndIsSolved(unittest.TestCase):
    def test_line_matches_clue(self):
        cases = [
            ([FILLED, GAP, FILLED], [1, 1], True),
            ([FILLED, FILLED, GAP], [2], True),
            ([FILLED, UNKNOWN, GAP], [1], False),
            ([FILLED, FILLED, GAP], [1, 1], False),
            ([GAP, GAP, GAP], [], True),
            ([FILLED, GAP, GAP], [], False),
        ]
        for cells, clue, expected in cases:
            with self.subTest(cells=cells, clue=clue):
                self.assertIs(line_matches_clue(cells, clue), expected)

    def test_is_solved_true_when_rows_and_columns_agree(self):
        puzzle = Puzzle(row_clues=[[3]], col_clues=[[1], [1], [1], [], []])
        puzzle.set_cell(1, 1, FILLED)
        puzzle.apply_line_solver("row", 1)
        self.assertTrue(puzzle.is_solved())

    def test_is_solved_false_when_axes_contradict(self):
        puzzle = Puzzle(row_clues=[[3]], col_clues=[[0]] * 5)
        puzzle.set_cell(1, 1, FILLED)
        puzzle.apply_line_solver("row", 1)
        self.assertFalse(puzzle.is_solved())


class TestApplyLineSolver(unittest.TestCase):
    def test_returns_changes(self):
        puzzle = Puzzle(row_clues=[[3]], col_clues=[[1], [1], [1], [], []])
        puzzle.set_cell(1, 1, FILLED)
        changes = puzzle.apply_line_solver("row", 1)
        self.assertEqual(
            sorted(changes),
            [(1, 2, FILLED), (1, 3, FILLED), (1, 4, GAP), (1, 5, GAP)],
        )
        self.assertEqual(puzzle.get_row(1), [FILLED, FILLED, FILLED, GAP, GAP])

    def test_nothing_deducible_returns_empty(self):
        puzzle = Puzzle(row_clues=[[3, 1]], col_clues=[[]] * 10)
        self.assertEqual(puzzle.apply_line_solver("row", 1), [])

    def test_contradiction_includes_label(self):
        puzzle = Puzzle(row_clues=[[3]], col_clues=[[1], [], [], [], []])
        puzzle.set_cell(1, 1, FILLED)
        puzzle.set_cell(1, 2, GAP)
        with self.assertRaisesRegex(LineContradiction, "Row 1"):
            puzzle.apply_line_solver("row", 1)

    def test_works_on_columns_too(self):
        puzzle = Puzzle(row_clues=[[1], [1], [1], [], []], col_clues=[[3]])
        puzzle.set_cell(1, 1, FILLED)
        changes = puzzle.apply_line_solver("col", 1)
        self.assertEqual(
            sorted(changes),
            [(2, 1, FILLED), (3, 1, FILLED), (4, 1, GAP), (5, 1, GAP)],
        )

    def test_invalid_kind_raises(self):
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        with self.assertRaises(ValueError):
            puzzle.apply_line_solver("diagonal", 1)


VALID_TEXT_NO_GRID = """
SIZE: 5x5
ROWS
1: 5
2: 0
3: 1,1,1
4: 0
5: 5
COLUMNS
1: 1,1
2: 1,1
3: 1,1,1
4: 1,1
5: 1,1
"""

VALID_TEXT_WITH_GRID = """
SIZE: 5x1
ROWS
1: 3
COLUMNS
1: 1
2: 1
3: 1
4: 0
5: 0
GRID
###xx
"""


class TestParsePuzzle(unittest.TestCase):
    def test_without_grid_section_loads_blank(self):
        puzzle, errors = parse_puzzle(VALID_TEXT_NO_GRID)
        self.assertEqual(errors, [])
        self.assertEqual(puzzle.get_row(1), [UNKNOWN] * 5)

    def test_grid_section_restores_marks(self):
        puzzle, errors = parse_puzzle(VALID_TEXT_WITH_GRID)
        self.assertEqual(errors, [])
        self.assertEqual(puzzle.get_row(1), [FILLED, FILLED, FILLED, GAP, GAP])

    def test_grid_row_starting_with_hash_is_not_a_comment(self):
        puzzle, errors = parse_puzzle(VALID_TEXT_WITH_GRID)
        self.assertEqual(errors, [])
        self.assertEqual(puzzle.get_cell(1, 1), FILLED)

    def test_missing_size_errors(self):
        text = "ROWS\n1: 3\nCOLUMNS\n1: 1\n"
        puzzle, errors = parse_puzzle(text)
        self.assertIsNone(puzzle)
        self.assertTrue(any("SIZE" in label for label, _ in errors))

    def test_missing_row_clue_errors(self):
        text = "SIZE: 2x2\nROWS\n1: 1\nCOLUMNS\n1: 1\n2: 1\n"
        puzzle, errors = parse_puzzle(text)
        self.assertIsNone(puzzle)
        self.assertTrue(any("Row 2" in label for label, _ in errors))

    def test_malformed_clue_line_errors(self):
        text = "SIZE: 1x1\nROWS\nnot-a-clue-line\nCOLUMNS\n1: 1\n"
        puzzle, errors = parse_puzzle(text)
        self.assertIsNone(puzzle)
        self.assertTrue(errors)

    def test_grid_wrong_row_count_errors(self):
        text = """
        SIZE: 5x1
        ROWS
        1: 3
        COLUMNS
        1: 1
        2: 1
        3: 1
        4: 0
        5: 0
        GRID
        ###xx
        xxxxx
        """
        puzzle, errors = parse_puzzle(text)
        self.assertIsNone(puzzle)
        self.assertTrue(any("GRID" in label for label, _ in errors))

    def test_grid_wrong_row_length_errors(self):
        text = """
        SIZE: 5x1
        ROWS
        1: 3
        COLUMNS
        1: 1
        2: 1
        3: 1
        4: 0
        5: 0
        GRID
        ###x
        """
        puzzle, errors = parse_puzzle(text)
        self.assertIsNone(puzzle)
        self.assertTrue(any("GRID" in label for label, _ in errors))

    def test_grid_invalid_character_errors(self):
        text = """
        SIZE: 5x1
        ROWS
        1: 3
        COLUMNS
        1: 1
        2: 1
        3: 1
        4: 0
        5: 0
        GRID
        ###x?
        """
        puzzle, errors = parse_puzzle(text)
        self.assertIsNone(puzzle)
        self.assertTrue(any("GRID" in label for label, _ in errors))


class TestPersistenceRoundTrip(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name)

    def test_save_and_load_round_trip(self):
        puzzle = Puzzle(row_clues=[[3]], col_clues=[[1], [1], [1], [], []])
        puzzle.set_cell(1, 1, FILLED)
        puzzle.apply_line_solver("row", 1)

        path = self.tmp_path / "puzzle.txt"
        save_puzzle(puzzle, path)
        loaded, errors = load_puzzle(path)

        self.assertEqual(errors, [])
        self.assertEqual(loaded.get_row(1), puzzle.get_row(1))
        self.assertEqual(loaded.row_clues, puzzle.row_clues)
        self.assertEqual(loaded.col_clues, puzzle.col_clues)
        self.assertTrue(loaded.is_solved())

    def test_save_preserves_blank_clue_as_zero(self):
        puzzle = Puzzle(row_clues=[[]], col_clues=[[], [], []])
        path = self.tmp_path / "puzzle.txt"
        save_puzzle(puzzle, path)
        loaded, errors = load_puzzle(path)
        self.assertEqual(errors, [])
        self.assertEqual(loaded.row_clues, [[]])
        self.assertEqual(loaded.col_clues, [[], [], []])


class TestApplyLineSolverRaw(unittest.TestCase):
    def test_raw_writes_cells_but_records_no_undo_step(self):
        # Blank row, clue [3] in a length-5 line: slack 2, so only the
        # overlap-guaranteed middle cell (position 3) is forced.
        puzzle = Puzzle(row_clues=[[3]], col_clues=[[1], [1], [1], [], []])
        changes = puzzle._apply_line_solver_raw("row", 1)
        self.assertEqual(changes, [(1, 3, UNKNOWN, FILLED)])
        self.assertEqual(puzzle.get_row(1), [UNKNOWN, UNKNOWN, FILLED, UNKNOWN, UNKNOWN])
        self.assertEqual(puzzle.undo(), [])  # nothing was recorded


# A plus-sign solution grid, used to build clues that are guaranteed
# consistent (derived from an actual filled grid, not hand-guessed):
#   ..#..
#   ..#..
#   #####
#   ..#..
#   ..#..
# Row 3 and column 3 are slack-0 (fully self-determined); every other
# row/column has clue [1] and only becomes determined once row 3 or
# column 3 supplies its one known cell - exactly the kind of two-hop
# dependency propagate()'s worklist needs to chase.
PLUS_ROW_CLUES = [[1], [1], [5], [1], [1]]
PLUS_COL_CLUES = [[1], [1], [5], [1], [1]]


class TestPropagate(unittest.TestCase):
    def test_cascades_across_multiple_lines_from_a_single_seed(self):
        puzzle = Puzzle(row_clues=PLUS_ROW_CLUES, col_clues=PLUS_COL_CLUES)
        changes = puzzle.propagate([(3, 3)])

        self.assertTrue(puzzle.is_solved())
        self.assertEqual(len(changes), 25)  # the whole 5x5 grid got resolved
        for row, col, new in changes:
            self.assertEqual(puzzle.get_cell(row, col), new)

        for r in (1, 2, 4, 5):
            self.assertEqual(puzzle.get_row(r), [GAP, GAP, FILLED, GAP, GAP])
        self.assertEqual(puzzle.get_row(3), [FILLED] * 5)

    def test_whole_cascade_is_one_undo_step(self):
        puzzle = Puzzle(row_clues=PLUS_ROW_CLUES, col_clues=PLUS_COL_CLUES)
        puzzle.propagate([(3, 3)])
        self.assertEqual(len(puzzle._undo_stack), 1)

        puzzle.undo()
        self.assertEqual(puzzle.get_row(1), [UNKNOWN] * 5)
        self.assertEqual(puzzle.get_row(3), [UNKNOWN] * 5)
        self.assertEqual(len(puzzle._undo_stack), 0)

    def test_redo_reapplies_the_whole_cascade(self):
        puzzle = Puzzle(row_clues=PLUS_ROW_CLUES, col_clues=PLUS_COL_CLUES)
        puzzle.propagate([(3, 3)])
        puzzle.undo()
        puzzle.redo()
        self.assertTrue(puzzle.is_solved())
        self.assertEqual(puzzle.get_row(3), [FILLED] * 5)

    def test_seed_with_no_deducible_info_yields_no_changes_and_no_step(self):
        # Neither row 1 nor column 1 has any known cell yet, and clue [1]
        # alone (in a length-5 line) doesn't pin down a position.
        puzzle = Puzzle(row_clues=PLUS_ROW_CLUES, col_clues=PLUS_COL_CLUES)
        changes = puzzle.propagate([(1, 1)])
        self.assertEqual(changes, [])
        self.assertEqual(puzzle.get_row(1), [UNKNOWN] * 5)
        self.assertEqual(puzzle.undo(), [])

    def test_seed_accepts_tuples_with_extra_elements(self):
        # apply_line_solver()/set_cell()-shaped (row, col, ...) tuples
        # should work directly as seeds, not just bare (row, col) pairs.
        puzzle = Puzzle(row_clues=PLUS_ROW_CLUES, col_clues=PLUS_COL_CLUES)
        changes = puzzle.propagate([(3, 3, FILLED)])
        self.assertEqual(len(changes), 25)
        self.assertTrue(puzzle.is_solved())

    def test_contradiction_mid_cascade_keeps_earlier_deductions(self):
        # Row 1 = [3] forces column 2/3 filled; columns 2-5 must be blank,
        # so column 2 contradicts once it's reached - but column 1's
        # valid deductions (made first) should survive.
        puzzle = Puzzle(
            row_clues=[[3], [1], [1], [1], [1]],
            col_clues=[[1], [], [], [], []],
        )
        puzzle.set_cell(1, 1, FILLED)
        self.assertEqual(len(puzzle._undo_stack), 1)

        with self.assertRaisesRegex(LineContradiction, "Column 2"):
            puzzle.propagate([(1, 1)])

        # Row 1 and column 1 were fully (and validly) resolved before the
        # contradiction in column 2 was hit.
        self.assertEqual(puzzle.get_row(1), [FILLED, FILLED, FILLED, GAP, GAP])
        self.assertEqual(puzzle.get_col(1), [FILLED, GAP, GAP, GAP, GAP])

        # The whole partial cascade is one combined step on top of the
        # manual set_cell step - not one step per line.
        self.assertEqual(len(puzzle._undo_stack), 2)

        puzzle.undo()
        self.assertEqual(puzzle.get_row(1), [FILLED, UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN])
        self.assertEqual(puzzle.get_col(1), [FILLED, UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN])
        self.assertEqual(len(puzzle._undo_stack), 1)

    def test_empty_seed_is_a_no_op(self):
        puzzle = Puzzle(row_clues=PLUS_ROW_CLUES, col_clues=PLUS_COL_CLUES)
        self.assertEqual(puzzle.propagate([]), [])
        self.assertEqual(len(puzzle._undo_stack), 0)


class TestUndoRedo(unittest.TestCase):
    def test_set_cell_records_single_step_and_undo_reverts_it(self):
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        puzzle.set_cell(1, 1, FILLED)
        puzzle.undo()
        self.assertEqual(puzzle.get_cell(1, 1), UNKNOWN)

    def test_set_cell_same_value_does_not_record_a_step(self):
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        puzzle.set_cell(1, 1, UNKNOWN)
        self.assertEqual(puzzle.undo(), [])

    def test_apply_line_solver_undo_reverts_whole_step_at_once(self):
        puzzle = Puzzle(row_clues=[[3]], col_clues=[[1], [1], [1], [], []])
        puzzle.set_cell(1, 1, FILLED)
        puzzle.apply_line_solver("row", 1)
        self.assertEqual(puzzle.get_row(1), [FILLED, FILLED, FILLED, GAP, GAP])

        puzzle.undo()
        self.assertEqual(puzzle.get_row(1), [FILLED, UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN])

    def test_apply_line_solver_with_no_changes_does_not_record_a_step(self):
        puzzle = Puzzle(row_clues=[[3, 1]], col_clues=[[]] * 10)
        puzzle.apply_line_solver("row", 1)
        self.assertEqual(puzzle.undo(), [])

    def test_redo_restores_after_undo(self):
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        puzzle.set_cell(1, 1, FILLED)
        puzzle.undo()
        puzzle.redo()
        self.assertEqual(puzzle.get_cell(1, 1), FILLED)

    def test_new_mutation_after_undo_clears_redo_stack(self):
        puzzle = Puzzle(row_clues=[[1], [1]], col_clues=[[2]])
        puzzle.set_cell(1, 1, FILLED)
        puzzle.undo()
        puzzle.set_cell(2, 1, FILLED)
        self.assertEqual(puzzle.redo(), [])

    def test_undo_on_empty_stack_returns_empty_list(self):
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        self.assertEqual(puzzle.undo(), [])

    def test_redo_on_empty_stack_returns_empty_list(self):
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        self.assertEqual(puzzle.redo(), [])


if __name__ == "__main__":
    unittest.main()
