"""Full-screen TUI for solving a live Puzzle interactively (textual).

The piece meant for actual day-to-day use - running alongside the
puzzle's source (a phone, a magazine) while solving, rather than
round-tripping through nonogram_repl.py's single-line prompts. Several
Tier 2 pieces (hint tiers, clue strikethrough) become visible here for
the first time: struck-through clue numbers only mean something once
there's a grid to render them against.

Design choice - the grid widget holds its own reactive copy of cell
state, synced via a posted "grid changed" message on every Puzzle
mutation, rather than re-reading Puzzle on every refresh:
NonogramGrid.CellsChanged carries the same (row, col, new_state) triples
apply_line_solver()/propagate()/undo()/redo() already return, applied
directly to the widget's own _cells cache in on_nonogram_grid_cells_changed().
This is what makes the "flash the newly-forced cells" requirement
cheap: the message already names exactly which cells to flash, with no
before/after diff against Puzzle needed. The widget does still hold a
read-only reference to the live Puzzle for the relatively rare,
already-computed queries (clues, solved_clue_indices) rather than
duplicating those too - only per-cell state, which changes on every
single action, is cached independently.

Rendering (row/column clue layout, cell styling) is split into plain
functions with no Textual dependency, so the actual layout math - the
part most likely to have an off-by-one - is unit-testable directly
against rich.text.Text's .plain string and .spans, without a running
App at all.
"""

import sys

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Footer, Header, Static

from .nonogram_overlap import FILLED, GAP, UNKNOWN
from .nonogram_linesolve import LineContradiction
from .nonogram_library import open_puzzle, save_to_library

CELL_WIDTH = 2

CELL_GLYPHS = {
    FILLED: "█" * CELL_WIDTH,
    GAP: "·" * CELL_WIDTH,
    UNKNOWN: " " * CELL_WIDTH,
}

CELL_STYLES = {
    FILLED: "bold white",
    GAP: "dim",
    UNKNOWN: "",
}

CURSOR_STYLE = "reverse"
FLASH_STYLE = "black on yellow"


def cell_style(state, is_cursor, is_flash):
    """The Rich style for one cell, layering cursor/flash highlights on
    top of its base FILLED/GAP/UNKNOWN look. Flash (a just-forced cell)
    takes priority over the plain cursor highlight so a flashed cell
    stays visible even if the cursor happens to be sitting on it;
    combined with "reverse" if both apply, so the cursor is still
    distinguishable.
    """
    base = CELL_STYLES[state]
    if is_flash and is_cursor:
        return f"{FLASH_STYLE} reverse"
    if is_flash:
        return FLASH_STYLE
    if is_cursor:
        return f"{base} {CURSOR_STYLE}".strip()
    return base


def row_clue_plain(clue):
    """The plain, unstyled text for one row's clue - "0" for blank."""
    return "0" if not clue else ", ".join(str(c) for c in clue)


def build_row_clue_text(clue, solved_indices, width):
    """A Rich Text of exactly `width` cells: one row's clue values,
    comma-separated and right-aligned, with any block whose index (1-
    indexed, matching Puzzle.solved_clue_indices) is in solved_indices
    struck through - the clue-strikethrough hint tier, made visible.
    """
    text = Text()
    if not clue:
        return text.append(row_clue_plain(clue).rjust(width))

    plain = row_clue_plain(clue)
    pad = max(0, width - len(plain))
    text.append(" " * pad)
    for i, size in enumerate(clue, start=1):
        if i > 1:
            text.append(", ")
        style = "strike dim" if i in solved_indices else "bold"
        text.append(str(size), style=style)
    return text


def build_col_header_lines(col_clues, col_solved, cell_width=CELL_WIDTH):
    """One Rich Text per header row (top to bottom), each
    len(col_clues) * cell_width cells wide: every column's clue values
    stacked vertically, bottom-aligned so the number nearest the grid
    is always the column's last block - the conventional nonogram
    layout - and right-aligned within its own cell_width slot.

    col_solved[c] is the solved_clue_indices() result for column c+1.
    """
    max_height = max((len(c) for c in col_clues), default=0)
    max_height = max(max_height, 1)

    lines = []
    for h in range(max_height):
        text = Text()
        for c, clue in enumerate(col_clues):
            length = len(clue)
            offset = max_height - length
            if h < offset:
                text.append(" " * cell_width)
                continue
            block_no = h - offset + 1
            value = clue[h - offset]
            style = "strike dim" if block_no in col_solved[c] else "bold"
            text.append(str(value).rjust(cell_width), style=style)
        lines.append(text)
    return lines


def safe_solved_indices(puzzle, kind, index):
    """puzzle.solved_clue_indices(), but a LineContradiction (a line
    whose current marks don't fit its clue at all) just means "nothing
    to strike through yet" for display purposes, rather than a reason
    to abort rendering the whole grid.
    """
    try:
        return set(puzzle.solved_clue_indices(kind, index))
    except LineContradiction:
        return set()


class NonogramGrid(Widget):
    """The core grid widget: clue headers along the top and left edges,
    one cell per (row, col) styled by its state, a movable cursor, and
    a brief flash on whatever cells a solving action just forced.

    Holds its own cache of cell state (_cells) rather than reading the
    live Puzzle on every render - see the module docstring for why.
    Everything else about the puzzle (dimensions, clues) is read
    straight from Puzzle, since that's fixed for the puzzle's lifetime
    and never needs cache invalidation.
    """

    can_focus = True
    cursor_row = reactive(0)
    cursor_col = reactive(0)

    FLASH_SECONDS = 1.2

    class CellsChanged(Message):
        """Posted to this widget whenever the live Puzzle's cells
        change, from any source - a manual mark, undo/redo, the line
        solver, propagation. `changes` is exactly the (row, col,
        new_state) list every mutating Puzzle method already returns,
        so this widget never has to diff old vs new to know what to
        flash.
        """

        def __init__(self, changes):
            self.changes = changes
            super().__init__()

    def __init__(self, puzzle):
        super().__init__()
        self.puzzle = puzzle
        self._cells = [[UNKNOWN] * puzzle.width for _ in range(puzzle.height)]
        self._flash = set()
        self._row_solved = [set() for _ in range(puzzle.height)]
        self._col_solved = [set() for _ in range(puzzle.width)]
        self._flash_timer = None

    def on_mount(self):
        self.load_from_puzzle()

    def load_from_puzzle(self):
        """Full resync from the live Puzzle - used once at startup and
        whenever a whole new Puzzle is swapped in (e.g. after 'load'),
        unlike CellsChanged's incremental per-action updates."""
        for r in range(self.puzzle.height):
            self._cells[r] = list(self.puzzle.get_row(r + 1))
        self._flash.clear()
        self.cursor_row = 0
        self.cursor_col = 0
        self._recompute_solved()
        self.refresh()

    def _recompute_solved(self):
        for r in range(self.puzzle.height):
            self._row_solved[r] = safe_solved_indices(self.puzzle, "row", r + 1)
        for c in range(self.puzzle.width):
            self._col_solved[c] = safe_solved_indices(self.puzzle, "col", c + 1)

    def on_nonogram_grid_cells_changed(self, message: "NonogramGrid.CellsChanged") -> None:
        for row, col, new in message.changes:
            self._cells[row - 1][col - 1] = new
        self._flash = {(row, col) for row, col, _ in message.changes}
        self._recompute_solved()
        self.refresh()

        if self._flash_timer is not None:
            self._flash_timer.stop()
        self._flash_timer = self.set_timer(self.FLASH_SECONDS, self._clear_flash)

    def _clear_flash(self):
        self._flash.clear()
        self.refresh()

    def render(self):
        puzzle = self.puzzle
        row_clue_width = max(
            (len(row_clue_plain(clue)) for clue in puzzle.row_clues), default=1
        )
        margin = " " * (row_clue_width + 1)

        text = Text()
        for line in build_col_header_lines(puzzle.col_clues, self._col_solved):
            text.append(margin)
            text.append(line)
            text.append("\n")

        for r in range(puzzle.height):
            text.append(build_row_clue_text(puzzle.row_clues[r], self._row_solved[r], row_clue_width))
            text.append(" ")
            for c in range(puzzle.width):
                state = self._cells[r][c]
                is_cursor = r == self.cursor_row and c == self.cursor_col
                is_flash = (r + 1, c + 1) in self._flash
                text.append(CELL_GLYPHS[state], style=cell_style(state, is_cursor, is_flash))
            text.append("\n")

        return text

    def move_cursor(self, dr, dc):
        self.cursor_row = max(0, min(self.puzzle.height - 1, self.cursor_row + dr))
        self.cursor_col = max(0, min(self.puzzle.width - 1, self.cursor_col + dc))


class NonogramApp(App):
    """The full-screen solving app: one live Puzzle, one NonogramGrid,
    and a status line reporting what the last action did (or why it
    was refused) - the same messages nonogram_repl.py's commands
    return, since the underlying actions are identical.
    """

    CSS = """
    NonogramGrid {
        width: auto;
        height: auto;
        padding: 1 2;
    }
    #status {
        height: auto;
        padding: 0 2;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("up", "move(-1,0)", "up", show=False),
        Binding("down", "move(1,0)", "down", show=False),
        Binding("left", "move(0,-1)", "left", show=False),
        Binding("right", "move(0,1)", "right", show=False),
        Binding("space", "mark_fill", "fill"),
        Binding("x", "mark_gap", "gap"),
        Binding("c", "mark_clear", "clear"),
        Binding("ctrl+z", "undo", "undo"),
        Binding("ctrl+y", "redo", "redo"),
        Binding("s", "solve", "solve line"),
        Binding("p", "propagate", "propagate"),
        Binding("P", "propagate_all", "propagate all"),
        Binding("h", "hint", "hint"),
        Binding("ctrl+s", "save", "save"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self, puzzle, library_id=None):
        super().__init__()
        self.puzzle = puzzle
        self.library_id = library_id

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield NonogramGrid(self.puzzle)
        yield Static(id="status")
        yield Footer()

    def on_mount(self):
        self.query_one(NonogramGrid).focus()
        self._set_status("Ready.")

    def _set_status(self, message, error=False):
        status = self.query_one("#status", Static)
        status.update(message)
        status.set_class(error, "-error")

    def _cursor_cell(self):
        grid = self.query_one(NonogramGrid)
        return grid.cursor_row + 1, grid.cursor_col + 1

    def _apply(self, changes, message):
        if changes:
            self.query_one(NonogramGrid).post_message(NonogramGrid.CellsChanged(changes))
        self._set_status(message)

    def action_move(self, dr, dc):
        self.query_one(NonogramGrid).move_cursor(dr, dc)

    def action_mark_fill(self):
        self._mark(FILLED)

    def action_mark_gap(self):
        self._mark(GAP)

    def action_mark_clear(self):
        self._mark(UNKNOWN)

    def _mark(self, state):
        row, col = self._cursor_cell()
        try:
            self.puzzle.set_cell(row, col, state)
        except LineContradiction as exc:
            self._set_status(f"Refused: {exc}", error=True)
            return
        self._apply([(row, col, state)], f"Marked ({row}, {col}).")

    def action_undo(self):
        changes = self.puzzle.undo()
        self._apply(changes, f"Undid {len(changes)} cell(s)." if changes else "Nothing to undo.")

    def action_redo(self):
        changes = self.puzzle.redo()
        self._apply(changes, f"Redid {len(changes)} cell(s)." if changes else "Nothing to redo.")

    def action_solve(self):
        row, col = self._cursor_cell()
        changes = []
        errors = []
        for kind, index in (("row", row), ("col", col)):
            try:
                changes += self.puzzle.apply_line_solver(kind, index)
            except LineContradiction as exc:
                errors.append(str(exc))
        if errors:
            self._apply(changes, f"Solved with errors: {'; '.join(errors)}")
        else:
            self._apply(changes, f"Forced {len(changes)} cell(s)." if changes else "No new deductions.")

    def action_propagate(self):
        row, col = self._cursor_cell()
        try:
            changes = self.puzzle.propagate([(row, col)])
        except LineContradiction as exc:
            self._set_status(f"Contradiction: {exc}", error=True)
            return
        self._apply(changes, f"Propagation forced {len(changes)} cell(s)." if changes else "No new deductions.")

    def action_propagate_all(self):
        puzzle = self.puzzle
        seeds = [(r, 1) for r in range(1, puzzle.height + 1)]
        seeds += [(1, c) for c in range(1, puzzle.width + 1)]
        try:
            changes = puzzle.propagate(seeds)
        except LineContradiction as exc:
            self._set_status(f"Contradiction: {exc}", error=True)
            return
        self._apply(changes, f"Propagation forced {len(changes)} cell(s)." if changes else "No new deductions.")

    def action_hint(self):
        row, col = self._cursor_cell()
        lines = self.puzzle.find_move_lines()
        if not lines:
            self._set_status("No line currently has a deducible move.")
            return
        labels = ", ".join(f"{'Row' if k == 'row' else 'Column'} {i}" for k, i in lines)

        here = ""
        for kind, index, label in (("row", row, f"Row {row}"), ("col", col, f"Column {col}")):
            cells = self.puzzle.find_move_cells(kind, index)
            if cells:
                shown = ", ".join(f"({r},{c})={v!r}" for r, c, v in cells)
                here = f" {label} would set: {shown}"
                break

        self._set_status(f"{len(lines)} line(s) have a move: {labels}.{here}")

    def action_save(self):
        if self.library_id is None:
            self._set_status("No library id for this puzzle - save it from the REPL first.", error=True)
            return
        save_to_library(self.puzzle, id=self.library_id)
        self._set_status(f"Saved as '{self.library_id}'.")


def main(argv):
    library_id = argv[1] if len(argv) > 1 else None
    if library_id is None:
        print("Usage: nonogram_tui.py <library-id>", file=sys.stderr)
        return 1
    try:
        puzzle = open_puzzle(library_id)
    except (KeyError, ValueError) as exc:
        print(f"Error loading '{library_id}': {exc}", file=sys.stderr)
        return 1
    NonogramApp(puzzle, library_id=library_id).run()
    return 0


def cli():
    """Console-script entry point (see pyproject.toml)."""
    sys.exit(main(sys.argv))


if __name__ == "__main__":
    cli()
