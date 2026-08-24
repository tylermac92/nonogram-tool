"""Tests for the full-screen TUI: nonogram_tui.py.

Two layers, matching nonogram_repl.py's test split:
  - Pure rendering functions (row/column clue layout, cell styling),
    tested directly against rich.text.Text's .plain and .spans with no
    Textual app running at all - this is where an off-by-one in the
    column-clue stacking math would actually show up.
  - The full App, driven end-to-end through Textual's own offline
    testing mechanism (App.run_test()/Pilot), so key bindings, the
    CellsChanged sync message, and the flash timer are genuinely
    exercised.
"""

import asyncio
import functools
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nonogram_overlap import FILLED, GAP, UNKNOWN
from nonogram_puzzle import Puzzle
import nonogram_library
from nonogram_tui import (
    NonogramApp,
    NonogramGrid,
    build_col_header_lines,
    build_row_clue_text,
    cell_style,
    row_clue_plain,
    safe_solved_indices,
)

DIAMOND_ROWS = [[1], [3], [5], [3], [1]]
DIAMOND_COLS = [[1], [3], [5], [3], [1]]


def make_puzzle():
    return Puzzle(row_clues=DIAMOND_ROWS, col_clues=DIAMOND_COLS)


class TestRowCluePlain(unittest.TestCase):
    def test_blank_clue_is_zero(self):
        self.assertEqual(row_clue_plain([]), "0")

    def test_joins_with_comma_space(self):
        self.assertEqual(row_clue_plain([19, 5, 53]), "19, 5, 53")


class TestBuildRowClueText(unittest.TestCase):
    def test_right_aligned_to_width(self):
        text = build_row_clue_text([19, 5, 53], set(), 12)
        self.assertEqual(text.plain, "   19, 5, 53")

    def test_blank_clue_shows_zero(self):
        text = build_row_clue_text([], set(), 5)
        self.assertEqual(text.plain, "    0")

    def test_solved_block_is_struck_through(self):
        text = build_row_clue_text([19, 5, 53], {2}, 12)
        struck = [s for s in text.spans if "strike" in s.style]
        self.assertEqual(len(struck), 1)
        span = struck[0]
        self.assertEqual(text.plain[span.start:span.end], "5")

    def test_no_solved_blocks_means_no_strikethrough(self):
        text = build_row_clue_text([19, 5, 53], set(), 12)
        self.assertFalse(any("strike" in s.style for s in text.spans))

    def test_exact_fit_needs_no_padding(self):
        text = build_row_clue_text([1], set(), 1)
        self.assertEqual(text.plain, "1")


class TestBuildColHeaderLines(unittest.TestCase):
    def test_uniform_height_one_line(self):
        lines = build_col_header_lines([[1], [3], [5]], [set(), set(), set()], cell_width=2)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].plain, " 1 3 5")

    def test_uneven_heights_are_bottom_aligned(self):
        # Column 0: [1] (1 block), column 1: [1, 1] (2 blocks, the
        # tallest), column 2: [3] (1 block) - shorter columns' numbers
        # sit in the bottom row, closest to the grid.
        lines = build_col_header_lines([[1], [1, 1], [3]], [set(), set(), set()], cell_width=2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].plain, "   1  ")
        self.assertEqual(lines[1].plain, " 1 1 3")

    def test_blank_column_clue_is_empty_not_zero(self):
        # Unlike a blank row (shown as "0"), a blank column just leaves
        # its header slot empty - the classic nonogram convention.
        lines = build_col_header_lines([[], [1]], [set(), set()], cell_width=2)
        self.assertEqual(lines[0].plain, "   1")

    def test_solved_block_struck_through_in_the_right_column(self):
        lines = build_col_header_lines(
            [[1], [3], [5]], [set(), set(), {1}], cell_width=2
        )
        struck = [s for s in lines[0].spans if "strike" in s.style]
        self.assertEqual(len(struck), 1)
        self.assertEqual(lines[0].plain[struck[0].start:struck[0].end].strip(), "5")

    def test_no_columns_still_returns_one_empty_line(self):
        lines = build_col_header_lines([], [], cell_width=2)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].plain, "")


class TestCellStyle(unittest.TestCase):
    def test_plain_states_have_no_highlight(self):
        self.assertNotIn("reverse", cell_style(FILLED, False, False))
        self.assertNotIn("yellow", cell_style(GAP, False, False))

    def test_cursor_adds_reverse(self):
        self.assertIn("reverse", cell_style(UNKNOWN, True, False))

    def test_flash_uses_distinct_highlight(self):
        style = cell_style(FILLED, False, True)
        self.assertIn("yellow", style)

    def test_flash_takes_priority_but_cursor_still_visible(self):
        style = cell_style(FILLED, True, True)
        self.assertIn("yellow", style)
        self.assertIn("reverse", style)


class TestSafeSolvedIndices(unittest.TestCase):
    def test_returns_the_real_result_when_feasible(self):
        puzzle = make_puzzle()
        self.assertEqual(safe_solved_indices(puzzle, "row", 3), {1})

    def test_contradiction_yields_empty_set_not_a_crash(self):
        puzzle = Puzzle(row_clues=[[3]], col_clues=[[1], [], [], [], []])
        puzzle.set_cell(1, 1, FILLED)
        puzzle._set_cell_raw(1, 2, GAP)  # bypass the eager guard to build a bad state
        self.assertEqual(safe_solved_indices(puzzle, "row", 1), set())


def run_app(coro_body, puzzle=None, library_id=None):
    """Run one async test body against a fresh NonogramApp via Textual's
    own pipe-free offline test harness (App.run_test()/Pilot)."""

    async def runner():
        app = NonogramApp(puzzle or make_puzzle(), library_id=library_id)
        async with app.run_test() as pilot:
            await coro_body(app, pilot)

    asyncio.run(runner())


class TestCursorMovement(unittest.TestCase):
    def test_arrows_move_the_cursor(self):
        async def body(app, pilot):
            grid = app.query_one(NonogramGrid)
            await pilot.press("right", "right", "down")
            self.assertEqual((grid.cursor_row, grid.cursor_col), (1, 2))

        run_app(body)

    def test_cursor_clamps_at_grid_edges(self):
        async def body(app, pilot):
            grid = app.query_one(NonogramGrid)
            await pilot.press(*["up"] * 5, *["left"] * 5)
            self.assertEqual((grid.cursor_row, grid.cursor_col), (0, 0))
            await pilot.press(*["down"] * 10, *["right"] * 10)
            self.assertEqual((grid.cursor_row, grid.cursor_col), (4, 4))

        run_app(body)


class TestMarking(unittest.TestCase):
    def test_space_marks_filled_and_updates_puzzle_and_cache(self):
        async def body(app, pilot):
            grid = app.query_one(NonogramGrid)
            grid.FLASH_SECONDS = 60  # not testing expiry - keep it from racing under load
            await pilot.press("down", "down", "space")
            await pilot.pause()
            self.assertEqual(app.puzzle.get_cell(3, 1), FILLED)
            self.assertEqual(grid._cells[2][0], FILLED)
            self.assertIn((3, 1), grid._flash)

        run_app(body)

    def test_x_marks_gap(self):
        async def body(app, pilot):
            await pilot.press("x")
            await pilot.pause()
            self.assertEqual(app.puzzle.get_cell(1, 1), GAP)

        run_app(body)

    def test_c_clears_back_to_unknown(self):
        async def body(app, pilot):
            await pilot.press("x", "c")
            await pilot.pause()
            self.assertEqual(app.puzzle.get_cell(1, 1), UNKNOWN)

        run_app(body)

    def test_refused_mark_reports_error_and_does_not_touch_the_cache(self):
        async def body(app, pilot):
            grid = app.query_one(NonogramGrid)
            await pilot.press("space")  # (1,1): col 1's blank clue can't take FILLED
            await pilot.pause()
            status = app.query_one("#status")
            self.assertTrue(status.has_class("-error"))
            self.assertIn("Refused", str(status.content))
            self.assertEqual(grid._cells[0][0], UNKNOWN)

        run_app(body, puzzle=Puzzle(row_clues=[[3]], col_clues=[[0]] * 5))


class TestFlash(unittest.TestCase):
    def test_flash_appears_then_clears_after_the_timer(self):
        async def body(app, pilot):
            grid = app.query_one(NonogramGrid)
            grid.FLASH_SECONDS = 1.0
            await pilot.press("space")
            await pilot.pause()
            self.assertEqual(grid._flash, {(1, 1)})
            await asyncio.sleep(1.5)
            await pilot.pause()
            self.assertEqual(grid._flash, set())

        run_app(body)

    def test_a_second_mutation_replaces_the_flash_set(self):
        async def body(app, pilot):
            grid = app.query_one(NonogramGrid)
            grid.FLASH_SECONDS = 60  # testing replacement, not expiry
            await pilot.press("space")
            await pilot.pause()
            self.assertEqual(grid._flash, {(1, 1)})
            # A cell sharing neither row nor column with (1,1), so this
            # mark can't conflict with the first one via either clue.
            await pilot.press("down", "down", "right", "right", "space")
            await pilot.pause()
            self.assertEqual(grid._flash, {(3, 3)})

        run_app(body)


class TestUndoRedo(unittest.TestCase):
    def test_undo_reverts_and_updates_the_cache(self):
        async def body(app, pilot):
            grid = app.query_one(NonogramGrid)
            await pilot.press("space", "ctrl+z")
            await pilot.pause()
            self.assertEqual(app.puzzle.get_cell(1, 1), UNKNOWN)
            self.assertEqual(grid._cells[0][0], UNKNOWN)

        run_app(body)

    def test_redo_reapplies(self):
        async def body(app, pilot):
            grid = app.query_one(NonogramGrid)
            await pilot.press("space", "ctrl+z", "ctrl+y")
            await pilot.pause()
            self.assertEqual(app.puzzle.get_cell(1, 1), FILLED)
            self.assertEqual(grid._cells[0][0], FILLED)

        run_app(body)

    def test_undo_with_nothing_to_undo_reports_so(self):
        async def body(app, pilot):
            await pilot.press("ctrl+z")
            await pilot.pause()
            status = app.query_one("#status")
            self.assertIn("Nothing to undo", str(status.content))

        run_app(body)


class TestSolveAndPropagate(unittest.TestCase):
    def test_solve_forces_the_cursor_row_and_column(self):
        async def body(app, pilot):
            grid = app.query_one(NonogramGrid)
            await pilot.press("right", "right", "down", "down", "s")  # cursor at (3,3)
            await pilot.pause()
            self.assertEqual(app.puzzle.get_row(3), [FILLED] * 5)
            self.assertEqual(grid._cells[2], [FILLED] * 5)

        run_app(body)

    def test_propagate_from_cursor_solves_the_whole_diamond(self):
        async def body(app, pilot):
            await pilot.press("right", "right", "down", "down", "p")
            await pilot.pause()
            self.assertTrue(app.puzzle.is_solved())

        run_app(body)

    def test_propagate_all_solves_without_a_seed_at_the_self_determining_line(self):
        async def body(app, pilot):
            await pilot.press("P")
            await pilot.pause()
            self.assertTrue(app.puzzle.is_solved())

        run_app(body)

    def test_propagate_reports_a_contradiction_without_crashing(self):
        async def body(app, pilot):
            await pilot.press("space")  # refused: nothing changes, so nothing to propagate from
            await pilot.press("p")
            await pilot.pause()
            # app is still alive and responsive
            status = app.query_one("#status")
            self.assertIsNotNone(status)

        run_app(body, puzzle=Puzzle(row_clues=[[3]], col_clues=[[0]] * 5))


class TestHint(unittest.TestCase):
    def test_reports_lines_with_a_move(self):
        async def body(app, pilot):
            await pilot.press("h")
            await pilot.pause()
            status = app.query_one("#status")
            self.assertIn("Row 3", str(status.content))
            self.assertIn("Column 3", str(status.content))

        run_app(body)

    def test_no_moves_reports_so(self):
        async def body(app, pilot):
            await pilot.press("h")
            await pilot.pause()
            status = app.query_one("#status")
            self.assertIn("No line currently has", str(status.content))

        run_app(body, puzzle=Puzzle(row_clues=[[1]] * 3, col_clues=[[1]] * 3))


class LibraryPatchedTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        library_dir = Path(self._tmpdir.name) / "puzzles"
        save_patch = patch(
            "nonogram_tui.save_to_library",
            functools.partial(nonogram_library.save_to_library, library_dir=library_dir),
        )
        save_patch.start()
        self.addCleanup(save_patch.stop)
        self.library_dir = library_dir


class TestSave(LibraryPatchedTestCase):
    def test_saves_under_the_given_library_id(self):
        async def body(app, pilot):
            await pilot.press("space", "ctrl+s")
            await pilot.pause()
            status = app.query_one("#status")
            self.assertIn("Saved as 'diamond'", str(status.content))

        run_app(body, library_id="diamond")
        self.assertTrue((self.library_dir / "diamond.txt").exists())

    def test_no_library_id_reports_an_error(self):
        async def body(app, pilot):
            await pilot.press("ctrl+s")
            await pilot.pause()
            status = app.query_one("#status")
            self.assertTrue(status.has_class("-error"))

        run_app(body, library_id=None)


class TestCellsChangedMessage(unittest.TestCase):
    def test_posting_directly_updates_the_cache_and_flash(self):
        async def body(app, pilot):
            grid = app.query_one(NonogramGrid)
            grid.FLASH_SECONDS = 60  # not testing expiry - keep it from racing under load
            grid.post_message(NonogramGrid.CellsChanged([(2, 2, FILLED), (2, 3, GAP)]))
            await pilot.pause()
            self.assertEqual(grid._cells[1][1], FILLED)
            self.assertEqual(grid._cells[1][2], GAP)
            self.assertEqual(grid._flash, {(2, 2), (2, 3)})

        run_app(body)


class TestInitialLoad(unittest.TestCase):
    def test_widget_cache_reflects_puzzle_state_already_set_before_mount(self):
        puzzle = make_puzzle()
        puzzle.set_cell(3, 3, FILLED)

        async def body(app, pilot):
            grid = app.query_one(NonogramGrid)
            self.assertEqual(grid._cells[2][2], FILLED)

        run_app(body, puzzle=puzzle)


class TestRenderIntegration(unittest.TestCase):
    def test_solved_line_shows_struck_clue_in_the_rendered_widget(self):
        async def body(app, pilot):
            grid = app.query_one(NonogramGrid)
            await pilot.press("right", "right", "down", "down", "s")  # solves row 3 and col 3
            await pilot.pause()
            text = grid.render()
            self.assertTrue(any("strike" in s.style for s in text.spans))
            self.assertIn("█" * 10, text.plain)  # row 3, fully filled

        run_app(body)


if __name__ == "__main__":
    unittest.main()
