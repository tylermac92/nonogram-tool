"""Interactive REPL driving a live Puzzle.

nonogram_overlap.py's repl() reports on one line at a time, from
scratch, on every call - there's no persistent state to lose. This REPL
is different: it drives one live Puzzle across many commands, so a
typo or a slip is a real, possibly-unrecoverable mistake rather than
"just run it again." That's the reasoning behind every choice below:

- prompt_toolkit's PromptSession replaces bare input() for arrow-key
  history and line editing - it doesn't change what any command does,
  only how comfortable typing a long session of them is.
- History is persisted to disk (FileHistory) rather than kept
  in-memory-only, since this REPL now carries real progress across
  runs, not just one-off line calculations.
- Commands go through a small dispatch table (COMMANDS), not a
  growing if/elif chain, precisely because the command surface here is
  bigger than "one line, one calculation": mark, solve, propagate,
  hint, undo, redo, save, load, triage.
- Every command that can mutate the grid re-renders it afterward
  (render_grid(), from nonogram_puzzle.py) - otherwise there would be
  no way to see progress in this mode at all.
- WordCompleter offers command-name autocomplete, built directly from
  the same COMMANDS table so the two can never drift apart.

This is the first third-party dependency in the project (everywhere
else is deliberately stdlib-only) - see requirements.txt.
"""

import shlex
import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory

from nonogram_overlap import FILLED, GAP, UNKNOWN, color_enabled
from nonogram_linesolve import LineContradiction
from nonogram_puzzle import render_grid, format_grid_triage_report
from nonogram_library import save_to_library, open_puzzle

DEFAULT_HISTORY_PATH = Path.home() / ".nonogram_repl_history"

QUIT_COMMANDS = {"q", "quit", "exit"}

_STATE_ALIASES = {
    "#": FILLED, "fill": FILLED, "filled": FILLED, "f": FILLED,
    "x": GAP, "gap": GAP, "g": GAP,
    ".": UNKNOWN, "unknown": UNKNOWN, "clear": UNKNOWN, "u": UNKNOWN,
}

_KIND_ALIASES = {"row": "row", "r": "row", "col": "col", "column": "col", "c": "col"}


class ReplError(Exception):
    """A command was misused - bad syntax, wrong argument, no puzzle
    loaded. Caught centrally in the REPL loop and shown as an error
    without stopping the session, the same way a bad manual mark or a
    line contradiction is."""


class ReplState:
    """The session's mutable context, threaded through every command
    handler: the live puzzle (if any), the library id it was last
    saved/loaded under (so a bare `save` can reuse it), and whether to
    colorize output."""

    def __init__(self, puzzle=None, use_color=False):
        self.puzzle = puzzle
        self.library_id = None
        self.use_color = use_color


def _require_puzzle(state):
    if state.puzzle is None:
        raise ReplError("No puzzle loaded - use 'load <id>' first.")


def _parse_int(token, name):
    try:
        return int(token)
    except ValueError:
        raise ReplError(f"'{token}' is not a valid {name}.")


def _parse_kind(token):
    kind = _KIND_ALIASES.get(token.lower())
    if kind is None:
        raise ReplError(f"'{token}' isn't row or col.")
    return kind


def _parse_cell_state(token):
    state = _STATE_ALIASES.get(token.lower())
    if state is None:
        raise ReplError(f"'{token}' isn't a cell state (use # / x / . or fill/gap/unknown).")
    return state


def _label(kind, index):
    return f"{'Row' if kind == 'row' else 'Column'} {index}"


def cmd_mark(state, args):
    _require_puzzle(state)
    if len(args) != 3:
        raise ReplError("Usage: mark <row> <col> <#/x/./fill/gap/unknown>")
    row = _parse_int(args[0], "row")
    col = _parse_int(args[1], "col")
    cell_state = _parse_cell_state(args[2])
    state.puzzle.set_cell(row, col, cell_state)
    return f"Marked ({row}, {col}) as {cell_state!r}."


def cmd_solve(state, args):
    _require_puzzle(state)
    if len(args) != 2:
        raise ReplError("Usage: solve <row|col> <n>")
    kind = _parse_kind(args[0])
    index = _parse_int(args[1], "index")
    changes = state.puzzle.apply_line_solver(kind, index)
    if not changes:
        return f"{_label(kind, index)}: no new deductions."
    cells = ", ".join(f"({r},{c})={v!r}" for r, c, v in changes)
    return f"{_label(kind, index)}: forced {len(changes)} cell(s): {cells}"


def cmd_propagate(state, args):
    _require_puzzle(state)
    puzzle = state.puzzle
    if not args or (len(args) == 1 and args[0].lower() == "all"):
        seeds = [(r, 1) for r in range(1, puzzle.height + 1)]
        seeds += [(1, c) for c in range(1, puzzle.width + 1)]
    elif len(args) == 2:
        seeds = [(_parse_int(args[0], "row"), _parse_int(args[1], "col"))]
    else:
        raise ReplError("Usage: propagate [<row> <col>]  (no args = whole grid)")
    changes = puzzle.propagate(seeds)
    return f"Propagation forced {len(changes)} cell(s)." if changes else "No new deductions."


def cmd_hint(state, args):
    _require_puzzle(state)
    puzzle = state.puzzle

    if not args:
        lines = puzzle.find_move_lines()
        if not lines:
            return "No line currently has a deducible move."
        labels = ", ".join(_label(k, i) for k, i in lines)
        return f"{len(lines)} line(s) have a move: {labels}"

    if len(args) == 2:
        kind = _parse_kind(args[0])
        index = _parse_int(args[1], "index")
        cells = puzzle.find_move_cells(kind, index)
        if not cells:
            return f"{_label(kind, index)}: no move right now."
        return f"{_label(kind, index)} would set: " + ", ".join(
            f"({r},{c})={v!r}" for r, c, v in cells
        )

    if len(args) == 3 and args[2].lower() == "why":
        kind = _parse_kind(args[0])
        index = _parse_int(args[1], "index")
        try:
            return puzzle.explain_line(kind, index)
        except ValueError as exc:
            raise ReplError(str(exc))

    raise ReplError("Usage: hint | hint <row|col> <n> | hint <row|col> <n> why")


def cmd_undo(state, args):
    _require_puzzle(state)
    changes = state.puzzle.undo()
    return f"Undid {len(changes)} cell(s)." if changes else "Nothing to undo."


def cmd_redo(state, args):
    _require_puzzle(state)
    changes = state.puzzle.redo()
    return f"Redid {len(changes)} cell(s)." if changes else "Nothing to redo."


def cmd_save(state, args):
    _require_puzzle(state)
    if len(args) > 2:
        raise ReplError("Usage: save [id] [title]")
    id = args[0] if len(args) >= 1 else state.library_id
    title = args[1] if len(args) == 2 else None
    saved_id = save_to_library(state.puzzle, id=id, title=title)
    state.library_id = saved_id
    return f"Saved as '{saved_id}'."


def cmd_load(state, args):
    if len(args) != 1:
        raise ReplError("Usage: load <id>")
    try:
        state.puzzle = open_puzzle(args[0])
    except (KeyError, ValueError) as exc:
        raise ReplError(str(exc))
    state.library_id = args[0]
    return f"Loaded '{args[0]}' ({state.puzzle.width}x{state.puzzle.height})."


def cmd_triage(state, args):
    _require_puzzle(state)
    if args not in ([], ["all"]):
        raise ReplError("Usage: triage [all]")
    return format_grid_triage_report(
        state.puzzle, use_color=state.use_color, show_solved=(args == ["all"])
    )


def cmd_help(state, args):
    lines = ["Commands:"]
    for name in sorted(COMMANDS):
        _, usage, _ = COMMANDS[name]
        lines.append(f"  {usage}")
    lines.append(f"  {'/'.join(sorted(QUIT_COMMANDS))} - leave the REPL")
    return "\n".join(lines)


# name -> (handler, usage text, mutates the grid)
COMMANDS = {
    "mark": (cmd_mark, "mark <row> <col> <state> - set one cell (state: # x . or fill/gap/unknown)", True),
    "solve": (cmd_solve, "solve <row|col> <n> - run the line solver on one row/column", True),
    "propagate": (cmd_propagate, "propagate [<row> <col>] - cascade deductions (no args = whole grid)", True),
    "hint": (cmd_hint, "hint | hint <row|col> <n> | hint <row|col> <n> why - never mutates", False),
    "undo": (cmd_undo, "undo - revert the last mutation", True),
    "redo": (cmd_redo, "redo - reapply the last undone mutation", True),
    "save": (cmd_save, "save [id] [title] - save to the puzzle library", False),
    "load": (cmd_load, "load <id> - load a puzzle from the library", True),
    "triage": (cmd_triage, "triage [all] - which lines are worth looking at next", False),
    "help": (cmd_help, "help - list commands", False),
}


def _build_session(history_path):
    words = sorted(COMMANDS) + sorted(QUIT_COMMANDS)
    return PromptSession(
        history=FileHistory(str(history_path)),
        completer=WordCompleter(words, ignore_case=True),
    )


def run_repl(puzzle=None, use_color=None, history_path=None, session=None):
    """Run the REPL loop until the user quits or input ends.

    puzzle: an optional Puzzle to start with (e.g. one just imported
    from a .non file or opened via the library from a wrapping script).
    Without one, only 'load' can supply a puzzle to work on.
    session: inject a pre-built PromptSession (e.g. one wired to
    prompt_toolkit's pipe input) for testing without a real terminal;
    normally left to be built from history_path.
    """
    if use_color is None:
        use_color = color_enabled()
    state = ReplState(puzzle=puzzle, use_color=use_color)

    if session is None:
        session = _build_session(history_path or DEFAULT_HISTORY_PATH)

    print("Nonogram REPL - type 'help' for commands, 'q' to quit.\n")

    while True:
        try:
            raw = session.prompt("nonogram> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        raw = raw.strip()
        if not raw:
            continue
        if raw.lower() in QUIT_COMMANDS:
            return 0

        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            continue

        name, args = parts[0].lower(), parts[1:]
        entry = COMMANDS.get(name)
        if entry is None:
            print(f"Unknown command: '{name}'. Type 'help' for a list.", file=sys.stderr)
            continue
        handler, _, mutates = entry

        try:
            result = handler(state, args)
        except (ReplError, LineContradiction, ValueError, KeyError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            continue

        if result:
            print(result)
        if mutates and state.puzzle is not None:
            print()
            print(render_grid(state.puzzle, use_color))
        print()


def main(argv):
    puzzle = None
    if len(argv) > 1:
        try:
            puzzle = open_puzzle(argv[1])
        except (KeyError, ValueError) as exc:
            print(f"Error loading '{argv[1]}': {exc}", file=sys.stderr)
            return 1
    return run_repl(puzzle=puzzle)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
