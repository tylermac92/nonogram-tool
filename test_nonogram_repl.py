"""Tests for the interactive Puzzle-driving REPL: nonogram_repl.py.

Two layers, matching how the module is actually exercised:
  - Command handlers (cmd_*) called directly against a ReplState, for
    focused correctness of what each command actually does.
  - The full run_repl() loop driven end-to-end through prompt_toolkit's
    pipe input, the same offline mechanism prompt_toolkit itself ships
    for testing PromptSession without a real terminal - so the dispatch
    loop, quit handling, and grid re-rendering are genuinely exercised,
    not just each handler in isolation.
"""

import functools
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from nonogram_overlap import FILLED, GAP, UNKNOWN
from nonogram_linesolve import LineContradiction
from nonogram_puzzle import Puzzle
import nonogram_library
import nonogram_repl
from nonogram_repl import (
    ReplError,
    ReplState,
    COMMANDS,
    QUIT_COMMANDS,
    cmd_help,
    cmd_hint,
    cmd_load,
    cmd_mark,
    cmd_propagate,
    cmd_redo,
    cmd_save,
    cmd_solve,
    cmd_triage,
    cmd_undo,
    run_repl,
    _parse_cell_state,
    _parse_int,
    _parse_kind,
)

# A 5x5 diamond: row/col 3 (clue [5]) are immediately self-determining;
# everything else needs propagation to resolve.
DIAMOND_ROWS = [[1], [3], [5], [3], [1]]
DIAMOND_COLS = [[1], [3], [5], [3], [1]]


def make_puzzle():
    return Puzzle(row_clues=DIAMOND_ROWS, col_clues=DIAMOND_COLS)


class TestParseHelpers(unittest.TestCase):
    def test_parse_int_accepts_digits(self):
        self.assertEqual(_parse_int("3", "row"), 3)

    def test_parse_int_rejects_non_digits(self):
        with self.assertRaisesRegex(ReplError, "row"):
            _parse_int("abc", "row")

    def test_parse_kind_accepts_aliases(self):
        for token in ("row", "r", "ROW"):
            self.assertEqual(_parse_kind(token), "row")
        for token in ("col", "c", "column", "COLUMN"):
            self.assertEqual(_parse_kind(token), "col")

    def test_parse_kind_rejects_unknown(self):
        with self.assertRaises(ReplError):
            _parse_kind("diagonal")

    def test_parse_cell_state_accepts_symbols_and_words(self):
        self.assertEqual(_parse_cell_state("#"), FILLED)
        self.assertEqual(_parse_cell_state("fill"), FILLED)
        self.assertEqual(_parse_cell_state("x"), GAP)
        self.assertEqual(_parse_cell_state("gap"), GAP)
        self.assertEqual(_parse_cell_state("."), UNKNOWN)
        self.assertEqual(_parse_cell_state("unknown"), UNKNOWN)

    def test_parse_cell_state_rejects_unknown_token(self):
        with self.assertRaises(ReplError):
            _parse_cell_state("purple")


class TestCommandHandlersRequirePuzzle(unittest.TestCase):
    """Every mutating/reading command should refuse cleanly, not crash,
    when no puzzle has been loaded yet."""

    def test_each_puzzle_dependent_command_raises_without_a_puzzle(self):
        state = ReplState(puzzle=None)
        for name, (handler, _, _) in COMMANDS.items():
            if name in ("load", "help"):
                continue
            with self.subTest(command=name):
                with self.assertRaises(ReplError):
                    handler(state, [])


class TestCmdMark(unittest.TestCase):
    def test_marks_the_cell(self):
        state = ReplState(puzzle=make_puzzle())
        result = cmd_mark(state, ["3", "3", "fill"])
        self.assertEqual(state.puzzle.get_cell(3, 3), FILLED)
        self.assertIn("(3, 3)", result)

    def test_wrong_arg_count_raises(self):
        state = ReplState(puzzle=make_puzzle())
        with self.assertRaises(ReplError):
            cmd_mark(state, ["3", "3"])

    def test_contradiction_propagates_as_line_contradiction(self):
        state = ReplState(puzzle=Puzzle(row_clues=[[3]], col_clues=[[0]] * 5))
        with self.assertRaises(LineContradiction):
            cmd_mark(state, ["1", "1", "fill"])


class TestCmdSolveAndPropagate(unittest.TestCase):
    def test_solve_forces_a_slack_zero_line(self):
        state = ReplState(puzzle=make_puzzle())
        result = cmd_solve(state, ["row", "3"])
        self.assertEqual(state.puzzle.get_row(3), [FILLED] * 5)
        self.assertIn("forced 5 cell", result)

    def test_solve_with_no_deduction_says_so(self):
        state = ReplState(puzzle=make_puzzle())
        result = cmd_solve(state, ["row", "1"])
        self.assertIn("no new deductions", result)

    def test_propagate_single_cell_seed(self):
        state = ReplState(puzzle=make_puzzle())
        result = cmd_propagate(state, ["3", "3"])
        self.assertTrue(state.puzzle.is_solved())
        self.assertIn("Propagation forced", result)

    def test_propagate_all_seeds_whole_grid(self):
        state = ReplState(puzzle=make_puzzle())
        cmd_mark(state, ["3", "3", "fill"])
        result = cmd_propagate(state, [])
        self.assertTrue(state.puzzle.is_solved())
        self.assertIn("Propagation forced", result)

    def test_propagate_bad_args_raises(self):
        state = ReplState(puzzle=make_puzzle())
        with self.assertRaises(ReplError):
            cmd_propagate(state, ["1"])


class TestCmdHint(unittest.TestCase):
    def test_no_args_lists_move_lines(self):
        state = ReplState(puzzle=make_puzzle())
        result = cmd_hint(state, [])
        self.assertIn("Row 3", result)
        self.assertIn("Column 3", result)

    def test_no_args_reports_when_nothing_has_a_move(self):
        state = ReplState(puzzle=Puzzle(row_clues=[[1]] * 3, col_clues=[[1]] * 3))
        result = cmd_hint(state, [])
        self.assertIn("No line currently has", result)

    def test_specific_line_shows_forced_cells(self):
        state = ReplState(puzzle=make_puzzle())
        result = cmd_hint(state, ["row", "3"])
        self.assertIn("would set", result)

    def test_specific_line_with_no_move_says_so(self):
        state = ReplState(puzzle=make_puzzle())
        result = cmd_hint(state, ["row", "1"])
        self.assertIn("no move right now", result)

    def test_why_reuses_explain_line_for_a_blank_line(self):
        state = ReplState(puzzle=make_puzzle())
        result = cmd_hint(state, ["row", "3", "why"])
        self.assertIn("STEP 1", result)

    def test_why_on_a_partially_known_line_raises_the_flagged_gap(self):
        state = ReplState(puzzle=make_puzzle())
        cmd_mark(state, ["1", "3", "fill"])
        with self.assertRaisesRegex(ReplError, "no partial-state explainer"):
            cmd_hint(state, ["row", "1", "why"])

    def test_bad_usage_raises(self):
        state = ReplState(puzzle=make_puzzle())
        with self.assertRaises(ReplError):
            cmd_hint(state, ["row", "1", "bogus", "extra"])


class TestCmdUndoRedo(unittest.TestCase):
    def test_undo_reverts_and_reports_nothing_when_empty(self):
        state = ReplState(puzzle=make_puzzle())
        self.assertIn("Nothing to undo", cmd_undo(state, []))
        cmd_mark(state, ["1", "3", "fill"])
        result = cmd_undo(state, [])
        self.assertIn("Undid 1 cell", result)
        self.assertEqual(state.puzzle.get_cell(1, 3), UNKNOWN)

    def test_redo_reapplies(self):
        state = ReplState(puzzle=make_puzzle())
        cmd_mark(state, ["1", "3", "fill"])
        cmd_undo(state, [])
        result = cmd_redo(state, [])
        self.assertIn("Redid 1 cell", result)
        self.assertEqual(state.puzzle.get_cell(1, 3), FILLED)


class LibraryPatchedTestCase(unittest.TestCase):
    """Points nonogram_repl's save/load at a temp library dir, so tests
    never touch the real default 'puzzles/' location."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        library_dir = Path(self._tmpdir.name) / "puzzles"

        save_patch = patch(
            "nonogram_repl.save_to_library",
            functools.partial(nonogram_library.save_to_library, library_dir=library_dir),
        )
        open_patch = patch(
            "nonogram_repl.open_puzzle",
            functools.partial(nonogram_library.open_puzzle, library_dir=library_dir),
        )
        save_patch.start()
        open_patch.start()
        self.addCleanup(save_patch.stop)
        self.addCleanup(open_patch.stop)


class TestCmdSaveLoad(LibraryPatchedTestCase):
    def test_save_then_load_round_trips(self):
        state = ReplState(puzzle=make_puzzle())
        cmd_mark(state, ["3", "3", "fill"])
        result = cmd_save(state, ["diamond", "Test Diamond"])
        self.assertIn("Saved as 'diamond'", result)
        self.assertEqual(state.library_id, "diamond")

        state2 = ReplState()
        result2 = cmd_load(state2, ["diamond"])
        self.assertIn("Loaded 'diamond'", result2)
        self.assertEqual(state2.puzzle.get_cell(3, 3), FILLED)

    def test_bare_save_reuses_the_last_id(self):
        state = ReplState(puzzle=make_puzzle())
        cmd_save(state, ["diamond"])
        cmd_mark(state, ["3", "3", "fill"])
        result = cmd_save(state, [])
        self.assertIn("Saved as 'diamond'", result)

    def test_load_unknown_id_raises_repl_error(self):
        state = ReplState()
        with self.assertRaises(ReplError):
            cmd_load(state, ["no-such-id"])

    def test_load_wrong_arg_count_raises(self):
        state = ReplState()
        with self.assertRaises(ReplError):
            cmd_load(state, [])


class TestCmdTriage(unittest.TestCase):
    def test_hides_solved_lines_by_default(self):
        state = ReplState(puzzle=make_puzzle())
        state.puzzle.propagate([(3, 3)])
        result = cmd_triage(state, [])
        self.assertIn("Nothing to show", result)

    def test_all_flag_shows_solved_lines(self):
        state = ReplState(puzzle=make_puzzle())
        state.puzzle.propagate([(3, 3)])
        result = cmd_triage(state, ["all"])
        self.assertIn("Row 1", result)

    def test_bad_usage_raises(self):
        state = ReplState(puzzle=make_puzzle())
        with self.assertRaises(ReplError):
            cmd_triage(state, ["bogus"])


class TestCmdHelp(unittest.TestCase):
    def test_lists_every_command_and_quit_words(self):
        result = cmd_help(ReplState(), [])
        for name in COMMANDS:
            self.assertIn(name, result)
        for word in QUIT_COMMANDS:
            self.assertIn(word, result)


class TestCommandTable(unittest.TestCase):
    def test_no_command_name_collides_with_a_quit_word(self):
        self.assertEqual(set(COMMANDS) & QUIT_COMMANDS, set())


def _run_pipe(commands, puzzle=None):
    """Feed a scripted command sequence through the real run_repl() loop
    via prompt_toolkit's pipe input, and capture everything printed -
    run_repl reports command errors on stderr, ordinary output on
    stdout, so both are merged into one buffer, the same as a user
    watching a real terminal would see them interleaved."""
    text = "\n".join(commands) + "\n"
    out = io.StringIO()
    with create_pipe_input() as pipe_input:
        pipe_input.send_text(text)
        session = PromptSession(input=pipe_input, output=DummyOutput())
        with redirect_stdout(out), redirect_stderr(out):
            rc = run_repl(puzzle=puzzle, use_color=False, session=session)
    return rc, out.getvalue()


class TestRunReplIntegration(unittest.TestCase):
    def test_quit_immediately_returns_zero(self):
        rc, output = _run_pipe(["q"])
        self.assertEqual(rc, 0)
        self.assertIn("Nonogram REPL", output)

    def test_eof_with_no_input_returns_cleanly(self):
        out = io.StringIO()
        with create_pipe_input() as pipe_input:
            # Closing the pipe with nothing written simulates Ctrl-D at
            # the very first prompt - session.prompt() raises EOFError.
            pipe_input.close()
            session = PromptSession(input=pipe_input, output=DummyOutput())
            with redirect_stdout(out):
                rc = run_repl(puzzle=None, use_color=False, session=session)
        self.assertEqual(rc, 0)

    def test_unknown_command_does_not_stop_the_session(self):
        rc, output = _run_pipe(["bogus", "help", "q"])
        self.assertEqual(rc, 0)
        self.assertIn("Unknown command", output)
        self.assertIn("Commands:", output)

    def test_blank_lines_are_skipped(self):
        rc, output = _run_pipe(["", "  ", "help", "q"])
        self.assertEqual(rc, 0)
        self.assertIn("Commands:", output)

    def test_mutating_command_reprints_the_grid(self):
        rc, output = _run_pipe(["mark 3 3 fill", "q"], puzzle=make_puzzle())
        self.assertIn("Marked (3, 3)", output)
        self.assertIn("#", output)  # the re-rendered grid

    def test_non_mutating_command_does_not_reprint_the_grid_twice(self):
        # hint never mutates - only the trailing blank-line separator
        # should follow it, no grid render.
        rc, output = _run_pipe(["hint", "q"], puzzle=make_puzzle())
        lines_between = output.split("have a move")[1].split("nonogram>")[0]
        self.assertNotIn("#", lines_between)

    def test_quoted_multi_word_argument_is_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            library_dir = Path(tmp) / "puzzles"
            with patch(
                "nonogram_repl.save_to_library",
                functools.partial(nonogram_library.save_to_library, library_dir=library_dir),
            ):
                rc, output = _run_pipe(
                    ['save diamond "Test Diamond"', "q"], puzzle=make_puzzle()
                )
        self.assertIn("Saved as 'diamond'", output)

    def test_shlex_parse_error_is_reported_not_raised(self):
        rc, output = _run_pipe(['mark 1 1 "unterminated', "q"], puzzle=make_puzzle())
        self.assertEqual(rc, 0)
        self.assertIn("Error", output)

    def test_contradiction_from_a_command_is_reported_not_raised(self):
        puzzle = Puzzle(row_clues=[[3]], col_clues=[[0]] * 5)
        rc, output = _run_pipe(["mark 1 1 fill", "q"], puzzle=puzzle)
        self.assertEqual(rc, 0)
        self.assertIn("Error", output)


if __name__ == "__main__":
    unittest.main()
