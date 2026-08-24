"""Persistent puzzle/grid state, built on top of nonogram_overlap.py."""

import re
from collections import deque

from .nonogram_overlap import (
    FILLED,
    GAP,
    UNKNOWN,
    LineError,
    _GREEN,
    _RED,
    analyze,
    build_table,
    colorize,
    format_report,
    paint,
    parse_clues,
    section,
)
from .nonogram_linesolve import solve_line, LineContradiction, _is_feasible, find_solved_blocks


def _diff_cells(known, solved, kind, index):
    """Yield (row, col, old, new) for every cell where solved disagrees
    with known, translating the line-local position back to grid
    coordinates. Shared by the code that writes these cells
    (_apply_line_solver_raw) and the code that only wants to preview them
    (find_move_cells).
    """
    for i, (old, new) in enumerate(zip(known, solved), start=1):
        if old == new:
            continue
        row, col = (index, i) if kind == "row" else (i, index)
        yield row, col, old, new


class Puzzle:
    """A nonogram's full state: every row/column's clue, plus the
    current mark (FILLED / GAP / UNKNOWN) of every cell.
    """

    def __init__(self, row_clues, col_clues):
        self.height = len(row_clues)
        self.width = len(col_clues)
        # Normalize "[0]" (a clue list containing the int 0) to "[]"
        # (the empty list) - parse_clues("0") already returns [], and
        # that's the only value line_matches_clue treats as "blank",
        # so anything built directly in Python needs to agree with it.
        self.row_clues = [[] if c == [0] else c for c in row_clues]
        self.col_clues = [[] if c == [0] else c for c in col_clues]
        self.grid = [[UNKNOWN] * self.width for _ in range(self.height)]
        self._undo_stack = []
        self._redo_stack = []

    def _row_index(self, row):
        if not (1 <= row <= self.height):
            raise ValueError(f"Row {row} is out of range (1-{self.height}).")
        return row - 1

    def _col_index(self, col):
        if not (1 <= col <= self.width):
            raise ValueError(f"Column {col} is out of range (1-{self.width}).")
        return col - 1

    def get_row(self, row):
        r = self._row_index(row)
        return list(self.grid[r])  # copy, so callers can't mutate state without set_cell

    def get_col(self, col):
        c = self._col_index(col)
        return [self.grid[r][c] for r in range(self.height)]

    def get_cell(self, row, col):
        r = self._row_index(row)
        c = self._col_index(col)
        return self.grid[r][c]

    def set_cell(self, row, col, state):
        """Mark one cell, refusing the write if it would make its row or
        column infeasible for their clues. The check runs against the
        state the grid would have *after* the write, but on rejection
        the write is undone before raising, so a caller never observes
        an inconsistent grid and no undo step is recorded for it. This
        catches a bad manual mark immediately, rather than leaving it
        to be discovered whenever a line solver next runs over that line
        (apply_line_solver/propagate already raise LineContradiction the
        same way once a line's actually examined - this exists for the
        gap before that: a bare manual mark propagation hasn't reached).
        """
        if state not in (FILLED, GAP, UNKNOWN):
            raise ValueError(f"Invalid cell state: {state!r}")

        old = self.get_cell(row, col)
        if old == state:
            return

        self._set_cell_raw(row, col, state)

        for kind, index, clue in (
            ("row", row, self.row_clues[row - 1]),
            ("col", col, self.col_clues[col - 1]),
        ):
            if not self.check_feasible(kind, index):
                self._set_cell_raw(row, col, old)  # refuse: leave the grid as it was
                label = f"{'Row' if kind == 'row' else 'Column'} {index}"
                raise LineContradiction(
                    f"{label}: marking ({row}, {col}) as {state!r} leaves no "
                    f"valid arrangement of {clue} for this line."
                )

        self._record_step([(row, col, old, state)])

    def check_feasible(self, kind, index):
        """Fast True/False: does this line's current known state still
        admit at least one valid arrangement of its clue? This is the
        same feasibility check solve_line already runs internally
        (_is_feasible) - exposed directly, with no attempt at deduction,
        as a cheap yes/no set_cell can call on every write.
        """
        known, clue = self._line_state(kind, index)
        return _is_feasible(clue, known)

    def apply_line_solver(self, kind, index):
        """Run the line solver on one row/column and record every forced
        cell as a single undo step. Returns the (row, col, new) changes.
        """
        step = self._apply_line_solver_raw(kind, index)
        self._record_step(step)
        return [(row, col, new) for row, col, old, new in step]

    def _apply_line_solver_raw(self, kind, index):
        """Like apply_line_solver, but writes forced cells directly
        without recording undo history. Callers that make several such
        calls in one logical action (apply_line_solver, propagate) group
        the returned (row, col, old, new) changes into their own step.
        """
        known, solved = self._solve_line(kind, index)
        step = []
        for row, col, old, new in _diff_cells(known, solved, kind, index):
            self._set_cell_raw(row, col, new)
            step.append((row, col, old, new))
        return step

    def _line_state(self, kind, index):
        """Return (known_cells, clue) for one row or column."""
        if kind == "row":
            return self.get_row(index), self.row_clues[index - 1]
        elif kind == "col":
            return self.get_col(index), self.col_clues[index - 1]
        else:
            raise ValueError(f"kind must be 'row' or 'col', got {kind!r}")

    def _solve_line(self, kind, index):
        """Return (known, solved) for one row/column: known is its
        current per-cell state, solved is what solve_line deduces from
        it - without writing anything back. Raises LineContradiction,
        labeled with the line, if the known cells don't fit the clue.
        """
        known, clue = self._line_state(kind, index)
        try:
            solved = solve_line(clue, known)
        except LineContradiction as exc:
            label = f"{'Row' if kind == 'row' else 'Column'} {index}"
            raise LineContradiction(f"{label}: {exc}") from exc
        return known, solved

    def _all_lines(self):
        """Yield (kind, index) for every row, then every column."""
        for r in range(1, self.height + 1):
            yield ("row", r)
        for c in range(1, self.width + 1):
            yield ("col", c)

    def has_any_move(self):
        """Hint tier 1: does any row or column currently have a
        deducible cell? Non-mutating - runs solve_line against the
        current grid but never writes the result back, so asking for a
        hint never changes the puzzle before the user accepts it.

        Short-circuits on the first line with a move; a LineContradiction
        on an already-inconsistent line propagates rather than being
        treated as "no move", consistent with apply_line_solver/propagate.
        """
        return any(self._line_has_move(kind, index) for kind, index in self._all_lines())

    def find_move_lines(self):
        """Hint tier 2: like has_any_move(), but returns every (kind,
        index) line that currently has a deducible cell instead of
        stopping at the first.
        """
        return [
            (kind, index)
            for kind, index in self._all_lines()
            if self._line_has_move(kind, index)
        ]

    def _line_has_move(self, kind, index):
        known, solved = self._solve_line(kind, index)
        return any(new != old for old, new in zip(known, solved))

    def find_move_cells(self, kind, index):
        """Hint tier 3: for one specific row/column, return the forced
        cells and their target states as (row, col, new) triples - the
        same shape apply_line_solver returns - without writing them.
        Empty list if the line has no deducible cell right now.
        """
        known, solved = self._solve_line(kind, index)
        return [(row, col, new) for row, col, old, new in _diff_cells(known, solved, kind, index)]

    def explain_line(self, kind, index):
        """Hint tier 4: human-readable reasoning for one line, reusing
        nonogram_overlap's format_report().

        Only works for a line that's still entirely UNKNOWN: format_report
        is built on analyze()'s blank-line slack/overlap technique, which
        has no notion of already-known cells. A line with partial state
        needs its own explainer - that doesn't exist yet, so this raises
        rather than silently handing back blank-line reasoning for a line
        it wasn't computed for.
        """
        known, clue = self._line_state(kind, index)
        if any(state != UNKNOWN for state in known):
            label = f"{'Row' if kind == 'row' else 'Column'} {index}"
            raise ValueError(
                f"{label} already has known cells - format_report() only "
                "explains a still-blank line; there's no partial-state "
                "explainer yet."
            )
        return format_report(analyze(len(known), clue))

    def solved_clue_indices(self, kind, index):
        """Which of this line's clue blocks currently have a start
        position that's the same in every valid arrangement - i.e.
        which physical clue number a future UI could strike through.
        Block 1 is always the leftmost clue, block 2 the next, and so
        on: a stable mapping independent of how much of the line is
        actually known.

        This needs its own reasoning (see
        nonogram_linesolve.find_solved_blocks) rather than being read
        off apply_line_solver's/solve_line's per-cell output: knowing a
        run of cells is forced FILLED doesn't by itself say which clue
        index it belongs to, especially before the line is fully solved.
        """
        known, _ = self._solve_line(kind, index)  # labeled LineContradiction if infeasible
        _, clue = self._line_state(kind, index)
        return [k + 1 for k in find_solved_blocks(clue, known)]

    def propagate(self, seed_changes):
        """Fixed-point constraint propagation from a set of just-changed
        cells: run the line solver on each seed cell's row and column,
        then chase every newly-forced cell into its cross line, until the
        worklist drains.

        seed_changes is an iterable of (row, col, ...) tuples - only the
        first two elements of each are used, so the return values of
        set_cell or apply_line_solver can be passed straight in.

        Returns the full list of (row, col, new) cells the cascade
        touched, not just the seed lines, so a future UI can highlight
        everything one action rippled into.

        If a line partway through the cascade turns out contradictory,
        everything deduced earlier in the same cascade is kept - it was
        validly derived from what was known at the time, so the
        contradiction lives in an already-marked cell, not in the
        propagation logic. The whole partial cascade is still recorded as
        one combined undo step before the LineContradiction is re-raised.
        """
        queue = deque()
        queued = set()

        def enqueue(kind, index):
            key = (kind, index)
            if key not in queued:
                queued.add(key)
                queue.append(key)

        for change in seed_changes:
            row, col = change[0], change[1]
            enqueue("row", row)
            enqueue("col", col)

        all_changes = []
        try:
            while queue:
                kind, index = queue.popleft()
                queued.discard((kind, index))
                changes = self._apply_line_solver_raw(kind, index)
                all_changes.extend(changes)
                for row, col, old, new in changes:
                    if kind == "row":
                        enqueue("col", col)
                    else:
                        enqueue("row", row)
        finally:
            self._record_step(all_changes)

        return [(row, col, new) for row, col, old, new in all_changes]

    def is_solved(self):
        rows_ok = all(
            line_matches_clue(self.get_row(r), self.row_clues[r - 1])
            for r in range(1, self.height + 1)
        )
        cols_ok = all(
            line_matches_clue(self.get_col(c), self.col_clues[c - 1])
            for c in range(1, self.width + 1)
        )
        return rows_ok and cols_ok

    def _set_cell_raw(self, row, col, state):
        """Write a cell directly, bypassing undo/redo tracking. Callers
        are responsible for recording history themselves - this exists
        so a multi-cell operation can build up one grouped undo step
        instead of several individual ones.
        """
        if state not in (FILLED, GAP, UNKNOWN):
            raise ValueError(f"Invalid cell state: {state!r}")
        r = self._row_index(row)
        c = self._col_index(col)
        self.grid[r][c] = state

    def _record_step(self, changes):
        """Push a grouped list of (row, col, old, new) as one undo
        step. Any new step invalidates whatever could previously be
        redone - a fresh mutation after an undo makes the undone
        branch unreachable.
        """
        if not changes:
            return
        self._undo_stack.append(changes)
        self._redo_stack.clear()

    def undo(self):
        """Revert the most recent step. Returns the list of
        (row, col, restored_state) cells that changed, or [] if
        there was nothing to undo.
        """
        if not self._undo_stack:
            return []
        step = self._undo_stack.pop()
        for row, col, old, new in step:
            self._set_cell_raw(row, col, old)
        self._redo_stack.append(step)
        return [(row, col, old) for row, col, old, new in step]

    def redo(self):
        """Re-apply the most recently undone step. Returns the list of
        (row, col, restored_state) cells that changed, or [] if
        there was nothing to redo.
        """
        if not self._redo_stack:
            return []
        step = self._redo_stack.pop()
        for row, col, old, new in step:
            self._set_cell_raw(row, col, new)
        self._undo_stack.append(step)
        return [(row, col, new) for row, col, old, new in step]


def line_matches_clue(cells, clue):
    """True if a *fully marked* line's filled runs exactly match clue.

    Only meaningful once every cell is FILLED or GAP - returns False
    if anything's still UNKNOWN, since the finished line isn't known
    yet. This is the narrow check is_solved() needs. Catching a
    contradiction *before* a line is finished needs real feasibility
    reasoning over partial state - that's the general line solver,
    not this function.
    """
    if UNKNOWN in cells:
        return False
    runs = []
    run_len = 0
    for ch in cells:
        if ch == FILLED:
            run_len += 1
        else:
            if run_len:
                runs.append(run_len)
            run_len = 0
    if run_len:
        runs.append(run_len)
    return runs == clue


_CLUE_LINE_RE = re.compile(r"^(\d+)\s*:\s*(.+)$")


def parse_puzzle(text):
    """Parse a SIZE/ROWS/COLUMNS[/GRID] block into a Puzzle plus a list
    of (label, message) errors. Returns (None, errors) if the text
    doesn't describe a complete puzzle.

    The GRID section is optional - a file without one loads as a blank
    puzzle, so older SIZE/ROWS/COLUMNS-only files still work unchanged.
    """
    width = height = None
    section = None
    row_clues = {}
    col_clues = {}
    grid_lines = []
    errors = []

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        if section == "grid":
            # Inside GRID data, '#' is a FILLED cell, not a comment
            # marker - every remaining non-blank line is a literal row.
            grid_lines.append((lineno, line))
            continue

        if line.startswith("#"):
            continue  # comment line (only recognized outside GRID data)

        upper = line.upper()

        if upper.startswith("SIZE"):
            _, _, value = line.partition(":")
            value = value.strip().lower()
            try:
                if "x" in value:
                    w_str, _, h_str = value.partition("x")
                    width, height = int(w_str.strip()), int(h_str.strip())
                else:
                    width = height = int(value)
            except ValueError:
                errors.append((f"line {lineno}", f"Invalid SIZE: '{line}'"))
            continue

        header = upper.rstrip(":").strip()
        if header in ("ROWS", "ROW"):
            section = "rows"
            continue
        if header in ("COLUMNS", "COLUMN", "COLS", "COL"):
            section = "columns"
            continue
        if header == "GRID":
            section = "grid"
            continue

        match = _CLUE_LINE_RE.match(line)
        if not match:
            errors.append((f"line {lineno}", f"Couldn't parse '{line}' (expected 'N: clues')"))
            continue

        number_str, clues_raw = match.groups()
        number = int(number_str)

        if section is None:
            errors.append((f"line {lineno}", "Clue line appears before a ROWS or COLUMNS header"))
            continue

        try:
            clues = parse_clues(clues_raw)
        except LineError as exc:
            label = f"{'Row' if section == 'rows' else 'Column'} {number}"
            errors.append((label, str(exc)))
            continue

        (row_clues if section == "rows" else col_clues)[number] = clues

    if width is None or height is None:
        errors.append(("SIZE", "No SIZE declared."))
        return None, errors

    missing_rows = [n for n in range(1, height + 1) if n not in row_clues]
    missing_cols = [n for n in range(1, width + 1) if n not in col_clues]
    for n in missing_rows:
        errors.append((f"Row {n}", "No clue given for this row."))
    for n in missing_cols:
        errors.append((f"Column {n}", "No clue given for this column."))
    if missing_rows or missing_cols:
        return None, errors

    ordered_row_clues = [row_clues[n] for n in range(1, height + 1)]
    ordered_col_clues = [col_clues[n] for n in range(1, width + 1)]
    puzzle = Puzzle(ordered_row_clues, ordered_col_clues)

    if grid_lines:
        if len(grid_lines) != height:
            errors.append(("GRID", f"Expected {height} grid row(s), got {len(grid_lines)}."))
            return None, errors
        valid_chars = {FILLED, GAP, UNKNOWN}
        for row_offset, (lineno, row_text) in enumerate(grid_lines, start=1):
            if len(row_text) != width:
                errors.append((
                    f"GRID line {lineno}",
                    f"Row {row_offset} has {len(row_text)} character(s), expected {width}.",
                ))
                return None, errors
            bad_chars = set(row_text) - valid_chars
            if bad_chars:
                errors.append((
                    f"GRID line {lineno}",
                    f"Unrecognized character(s) {sorted(bad_chars)} in row {row_offset}.",
                ))
                return None, errors
            for col_offset, ch in enumerate(row_text, start=1):
                puzzle.set_cell(row_offset, col_offset, ch)

    return puzzle, errors


def save_puzzle(puzzle, path):
    """Write a Puzzle to path in the SIZE/ROWS/COLUMNS/GRID text format."""
    lines = [f"SIZE: {puzzle.width}x{puzzle.height}", "", "ROWS"]
    for i, clue in enumerate(puzzle.row_clues, start=1):
        clue_str = "0" if not clue else ",".join(str(c) for c in clue)
        lines.append(f"{i}: {clue_str}")
    lines += ["", "COLUMNS"]
    for i, clue in enumerate(puzzle.col_clues, start=1):
        clue_str = "0" if not clue else ",".join(str(c) for c in clue)
        lines.append(f"{i}: {clue_str}")
    lines += ["", "GRID"]
    for row in range(1, puzzle.height + 1):
        lines.append("".join(puzzle.get_row(row)))

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def load_puzzle(path):
    """Read a puzzle file. Returns (puzzle_or_None, errors), same
    convention as parse_puzzle.
    """
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return parse_puzzle(text)


def render_grid(puzzle, use_color=False):
    """A simple text rendering of the whole live grid: a top ruler, then
    one row per puzzle row, each prefixed with its row number.

    Deliberately not built on nonogram_overlap's ruler()/render_line() -
    those hardcode a 2-space left margin sized for their own single-line
    report layout, which doesn't fit a grid whose row-number column
    varies with puzzle height. colorize() is reused as-is, though - it's
    already generic over any FILLED/GAP/UNKNOWN string.
    """
    height, width = puzzle.height, puzzle.width
    label_width = len(str(height))
    indent = " " * (label_width + 1)

    marks = [" "] * width
    for pos in range(5, width + 1, 5):
        digits = str(pos)
        start = pos - len(digits)
        for i, ch in enumerate(digits):
            marks[start + i] = ch
    lines = [indent + "".join(marks)]

    for r in range(1, height + 1):
        row_text = "".join(puzzle.get_row(r))
        label = str(r).rjust(label_width)
        lines.append(f"{label} {colorize(row_text, use_color)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Batch/triage on a live grid
# ---------------------------------------------------------------------------
#
# nonogram_overlap.py's parse_batch()/format_batch_report() triage a flat
# clue-list text block against analyze()'s blank-line slack technique -
# there's no known grid state involved at all. This is the alternative
# entry point for the other input shape the same idea makes sense for: a
# live Puzzle, where the interesting question per line isn't slack (a
# blank-line-only concept) but how many cells are still UNKNOWN and
# whether the line has a move available right now. It lives here rather
# than in nonogram_overlap.py because it needs Puzzle and its grid state,
# which nonogram_overlap.py (a lower layer Puzzle is built on) can't
# import without a cycle - so "the batch/triage entry point" is really
# two sibling functions in their natural layers, format_batch_report()
# for flat clue-list text and format_grid_triage_report() here for a
# live Puzzle, rather than one function overloaded across the two.


def _line_triage_entries(puzzle):
    """One entry per row and column of a live Puzzle: how many cells are
    still UNKNOWN, and whether the line currently has a pending move.

    The move check reuses Puzzle._line_has_move() - the exact per-line
    primitive find_move_lines() (hint tier 2) is built from - so this
    doesn't re-derive "does this line have a move" independently. Unlike
    find_move_lines(), a LineContradiction on one line doesn't abort the
    whole scan: it's collected the same way parse_batch() collects
    per-line errors, so one bad line doesn't stop the rest of the puzzle
    from being triaged.

    Returns (entries, contradictions).
    """
    entries = []
    contradictions = []

    for kind, index in puzzle._all_lines():
        known, clue = puzzle._line_state(kind, index)
        label = f"{'Row' if kind == 'row' else 'Column'} {index}"
        length = len(known)
        unknown = known.count(UNKNOWN)
        resolved = length - unknown
        pct = 100.0 * resolved / length if length else 100.0

        try:
            has_move = puzzle._line_has_move(kind, index)
        except LineContradiction as exc:
            # str(exc) already reads "Row N: ..."/"Column N: ..." - it's
            # _solve_line's own labeled message, not a bare one - so it's
            # stored and shown as-is rather than prefixed with `label`
            # again.
            contradictions.append(str(exc))
            has_move = None

        entries.append(
            {
                "kind": kind,
                "index": index,
                "label": label,
                "length": length,
                "clue": clue,
                "unknown": unknown,
                "resolved": resolved,
                "pct": pct,
                "has_move": has_move,
            }
        )

    return entries, contradictions


def _triage_sort_key(entry):
    """Solved lines (nothing left to triage) first, then lines with a
    pending move, then everything else - ascending unknown-cell count
    within each group, so the closest-to-done lines surface first."""
    if entry["unknown"] == 0:
        priority = 0
    elif entry["has_move"]:
        priority = 1
    else:
        priority = 2
    return (priority, entry["unknown"], entry["kind"], entry["index"])


def format_grid_triage_report(puzzle, use_color=False, show_solved=False, max_unknown=None):
    """Triage report for a live Puzzle: which rows/columns are worth
    looking at next, ranked by how close each is to done.

    A fully-solved line (no UNKNOWN cells left) has nothing left to
    triage, so it's hidden by default - pass show_solved=True to list
    it anyway. max_unknown, if given, additionally hides any line with
    more than that many UNKNOWN cells remaining (the filter idea from
    the original slack-threshold sketch, reframed around this metric:
    "only show lines with N or fewer unknown cells left" instead of "only
    show lines under this slack").

    Lines whose current marks don't fit their clue at all are reported
    separately as contradictions, not ranked alongside solvable lines -
    a broken line isn't "close to done", it needs attention.
    """
    entries, contradictions = _line_triage_entries(puzzle)

    total_lines = len(entries)
    solved_count = sum(1 for e in entries if e["unknown"] == 0)
    move_count = sum(1 for e in entries if e["has_move"])
    total_cells = puzzle.width * puzzle.height
    resolved_cells = sum(e["resolved"] for e in entries if e["kind"] == "row")
    pct_all = 100.0 * resolved_cells / total_cells if total_cells else 100.0

    out = []
    title = (
        f" GRID TRIAGE - {total_lines} line{'s' if total_lines != 1 else ''} "
        f"({solved_count} solved, {move_count} with a move, "
        f"{len(contradictions)} contradiction{'s' if len(contradictions) != 1 else ''}) "
    )
    out.append("=" * len(title))
    out.append(title)
    out.append("=" * len(title))
    out.append("")
    out.append(
        f"Overall: {resolved_cells} of {total_cells} cells filled ({pct_all:.0f}%) - "
        f"{solved_count} of {total_lines} lines fully solved."
    )
    out.append("")

    visible = [e for e in entries if show_solved or e["unknown"] > 0]
    if max_unknown is not None:
        visible = [e for e in visible if e["unknown"] <= max_unknown]
    visible.sort(key=_triage_sort_key)

    if visible:
        out.append(
            "Sorted by priority: lines with a pending move first, then by "
            "ascending unknown-cell count."
        )
        out.append("")

        headers = ["#", "line", "len", "clue", "unknown", "resolved", "%", "move?"]
        rows = []
        solved_flags = []
        for rank, entry in enumerate(visible, start=1):
            clue_display = "0 (blank)" if not entry["clue"] else ", ".join(
                str(c) for c in entry["clue"]
            )
            rows.append(
                [
                    str(rank),
                    entry["label"],
                    str(entry["length"]),
                    clue_display,
                    str(entry["unknown"]),
                    str(entry["resolved"]),
                    f"{entry['pct']:.0f}%",
                    "yes" if entry["has_move"] else "-",
                ]
            )
            solved_flags.append(entry["unknown"] == 0)

        table_lines = build_table(headers, rows)
        out.append(table_lines[0])
        out.append(table_lines[1])
        for is_solved, row_line in zip(solved_flags, table_lines[2:]):
            out.append(paint(row_line, _GREEN, use_color) if is_solved else row_line)
        out.append("")
    elif entries:
        out.append("(Nothing to show - try show_solved=True or a higher max_unknown.)")
        out.append("")

    if contradictions:
        out.extend(section(f"CONTRADICTIONS ({len(contradictions)})"))
        for message in contradictions:
            out.append(paint(f"  {message}", _RED, use_color))
        out.append("")

    return "\n".join(out)

if __name__ == "__main__":
    puzzle = Puzzle(row_clues=[[3]], col_clues=[[1], [1], [1], [], []])

    puzzle.set_cell(1, 1, FILLED)
    print("after manual mark:", puzzle.get_row(1), "| undo stack size:", len(puzzle._undo_stack))

    puzzle.apply_line_solver("row", 1)
    print("after solver:     ", puzzle.get_row(1), "| undo stack size:", len(puzzle._undo_stack))

    puzzle.undo()  # should revert ALL 4 solver-forced cells in one call
    print("after one undo:   ", puzzle.get_row(1))

    puzzle.undo()  # should revert the original manual mark too
    print("after second undo:", puzzle.get_row(1), "| undo stack size:", len(puzzle._undo_stack))

    puzzle.redo()
    puzzle.redo()
    print("after two redos:  ", puzzle.get_row(1))

    puzzle.undo()
    puzzle.set_cell(1, 5, GAP)  # a fresh mutation after an undo
    print("redo after new mutation:", puzzle.redo(), "(should be [] - redo branch is gone)")
