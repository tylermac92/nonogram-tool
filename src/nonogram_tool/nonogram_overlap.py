#!/usr/bin/env python3
"""
Nonogram overlap solver (slack method).

Given a line length and its clues, computes which cells are guaranteed filled
using the overlap/slack technique:

    minLen = sum(clues) + (len(clues) - 1)
    slack  = N - minLen

For each block i (1-indexed leftmost start), if size > slack:
    guaranteed range = [start + slack, start + size - 1]

Usage:
    python nonogram_overlap.py 80 19,5,53
    python nonogram_overlap.py            # interactive loop - keeps
                                           # prompting for lines until
                                           # you type 'q'
    python nonogram_overlap.py 80 "19 5 53"

    python nonogram_overlap.py --batch puzzle.txt          # whole puzzle
    python nonogram_overlap.py --batch puzzle.txt --full   # + full detail
    python nonogram_overlap.py --batch            # paste block, then Ctrl-D

    Batch input format:
        SIZE: 80x80
        ROWS
        1: 19,5,53
        2: 5,2,27,6,11
        COLUMNS
        1: 46,6,17
        ...

Color: ANSI colors highlight filled/gap/unknown cells automatically when
output goes to a real terminal. Disable with NO_COLOR=1, per no-color.org.
"""

import os
import re
import sys

FILLED = "#"
UNKNOWN = "."
GAP = "x"

# ANSI colors, keyed by the character they decorate.
_RESET = "\033[0m"
_COLORS = {
    FILLED: "\033[1;32m",  # bold green - guaranteed filled
    GAP: "\033[31m",  # red - forced empty
    UNKNOWN: "\033[2m",  # dim - still unknown
}


def color_enabled():
    """Auto-detect whether ANSI color is appropriate: a real terminal, and
    the user hasn't opted out via the NO_COLOR convention (https://no-color.org/)."""
    if os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty()


def colorize(text, enabled):
    """Wrap runs of FILLED/GAP/UNKNOWN characters in their ANSI color.
    Grouping into runs (rather than coloring char-by-char) keeps the escape
    sequences down to one per contiguous block instead of one per cell."""
    if not enabled:
        return text
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        j = i
        while j < n and text[j] == ch:
            j += 1
        color = _COLORS.get(ch)
        segment = text[i:j]
        out.append(f"{color}{segment}{_RESET}" if color else segment)
        i = j
    return "".join(out)


# Aliases for painting arbitrary text (table rows, error messages) - reuses
# the same three-color palette as colorize() for a consistent visual language.
_GREEN = _COLORS[FILLED]
_RED = _COLORS[GAP]
_DIM = _COLORS[UNKNOWN]


def paint(text, color, enabled):
    """Wrap a whole string in a raw ANSI color code. Unlike colorize(), this
    doesn't inspect characters - it's for coloring things like a whole table
    row or error message after it's already been formatted, so column
    alignment (computed on the plain text) is never affected."""
    return f"{color}{text}{_RESET}" if enabled else text


class LineError(ValueError):
    """Raised when a line's clues can't fit in the given length."""


def parse_clues(raw):
    """Parse clues from a string separated by commas, spaces, or both.

    A single clue of 0 is standard nonogram notation for "this line has no
    blocks at all" (an entirely empty row/column). It's returned as an empty
    list, since there's nothing to place. 0 can't be combined with other
    clues - a line either has real blocks or is blank, never both.
    """
    parts = [p for p in re.split(r"[,\s]+", raw.strip()) if p]
    if not parts:
        raise LineError("No clues provided.")
    clues = []
    for p in parts:
        try:
            value = int(p)
        except ValueError:
            raise LineError(f"'{p}' is not a valid integer clue.")
        if value < 0:
            raise LineError(f"Clue values must be non-negative (got {value}).")
        clues.append(value)

    if 0 in clues:
        if len(clues) > 1:
            raise LineError(
                "A clue of 0 means the line is entirely empty and can't be "
                "combined with other clues (got "
                f"{', '.join(str(c) for c in clues)})."
            )
        return []  # Blank line: no blocks.

    return clues


def analyze(length, clues):
    """Run the full slack/overlap calculation for one line."""
    if length <= 0:
        raise LineError("Line length must be positive.")

    if not clues:
        # Blank line (clue "0"): no blocks, every cell is guaranteed empty.
        return {
            "length": length,
            "clues": [],
            "is_blank": True,
            "sum": 0,
            "gaps": 0,
            "min_len": 0,
            "slack": length,
            "blocks": [],
            "total_guaranteed": 0,
        }

    total = sum(clues)
    gaps = len(clues) - 1
    min_len = total + gaps
    slack = length - min_len

    if slack < 0:
        raise LineError(
            f"Clues don't fit: they need at least {min_len} cells "
            f"but the line is only {length}."
        )

    # Leftmost start position of each block, 1-indexed.
    blocks = []
    start = 1
    for size in clues:
        if size > slack:
            g_start = start + slack
            g_end = start + size - 1
            g_count = size - slack
        else:
            g_start = g_end = None
            g_count = 0
        blocks.append(
            {
                "size": size,
                "start": start,
                "left_end": start + size - 1,
                "g_start": g_start,
                "g_end": g_end,
                "g_count": g_count,
            }
        )
        start += size + 1

    return {
        "is_blank": False,
        "length": length,
        "clues": clues,
        "sum": total,
        "gaps": gaps,
        "min_len": min_len,
        "slack": slack,
        "blocks": blocks,
        "total_guaranteed": sum(b["g_count"] for b in blocks),
    }


def render_line(result):
    """Build a single-row ASCII picture of the line with guaranteed cells marked."""
    length = result["length"]
    cells = [UNKNOWN] * length

    if result["slack"] == 0:
        # Fully determined: fill blocks and mark the forced gaps between them.
        for b in result["blocks"]:
            for i in range(b["start"], b["left_end"] + 1):
                cells[i - 1] = FILLED
        for idx, ch in enumerate(cells):
            if ch == UNKNOWN:
                cells[idx] = GAP
    else:
        for b in result["blocks"]:
            if b["g_start"] is None:
                continue
            for i in range(b["g_start"], b["g_end"] + 1):
                cells[i - 1] = FILLED

    return "  " + "".join(cells)


def ruler(length):
    """A tick mark every 5 cells, aligned to render_line's 2-space prefix."""
    marks = [" "] * length
    for pos in range(5, length + 1, 5):
        label = str(pos)
        start = pos - len(label)
        for i, ch in enumerate(label):
            marks[start + i] = ch
    return "  " + "".join(marks)


def build_table(headers, rows):
    """Format a table with column widths sized to the actual content, so the
    header, divider, and every row always line up exactly - no matter how
    large the clue numbers or cell ranges get."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells):
        return "  " + "  ".join(cell.rjust(widths[i]) for i, cell in enumerate(cells))

    header_line = fmt_row(headers)
    divider = "  " + "-" * (len(header_line) - 2)

    lines = [header_line, divider]
    lines.extend(fmt_row(row) for row in rows)
    return lines


def section(title):
    """A section title followed by a divider matching its exact width."""
    return [title, "-" * len(title)]


def format_report(result, use_color=False):
    """Produce the full human-readable report for a line."""
    out = []
    clues_str = "0 (blank line)" if result["is_blank"] else ", ".join(
        str(c) for c in result["clues"]
    )
    header = f" Line length {result['length']}  |  clues: {clues_str} "
    out.append("=" * len(header))
    out.append(header)
    out.append("=" * len(header))
    out.append("")

    if result["is_blank"]:
        out.extend(section("BLANK LINE"))
        out.append("  A clue of 0 means this line has no blocks at all.")
        out.append(f"  All {result['length']} cells are guaranteed empty.")
        out.append("")
        out.extend(section("LINE"))
        out.append(f"  '{colorize(GAP, use_color)}' = forced empty")
        out.append(ruler(result["length"]))
        out.append(colorize("  " + GAP * result["length"], use_color))
        out.append("")
        return "\n".join(out)

    # --- Step 1 -------------------------------------------------------
    out.extend(section("STEP 1 - Slack"))
    out.append(f"  S       = {' + '.join(str(c) for c in result['clues'])} = {result['sum']}")
    out.append(f"  G       = {len(result['clues'])} - 1 = {result['gaps']}")
    out.append(f"  minLen  = {result['sum']} + {result['gaps']} = {result['min_len']}")
    out.append(f"  slack   = {result['length']} - {result['min_len']} = {result['slack']}")
    out.append("")

    if result["slack"] == 0:
        out.append("  ** slack = 0 -> the line is fully determined. Fill it completely. **")
        out.append("")
    elif result["total_guaranteed"] == 0:
        out.append(
            f"  ** No block is larger than the slack ({result['slack']}). "
            "No guaranteed cells in this line yet. **"
        )
        out.append("")

    # --- Steps 2 & 3 --------------------------------------------------
    out.extend(section("STEPS 2 & 3 - Block starts and guaranteed ranges"))

    headers = ["#", "size", "start", "leftmost", "count", "guaranteed"]
    rows = []
    for idx, b in enumerate(result["blocks"], start=1):
        leftmost = f"{b['start']}-{b['left_end']}"
        if b["g_start"] is None:
            count = "0"
            guaranteed = "(none)"
        else:
            count = str(b["g_count"])
            guaranteed = f"{b['g_start']}-{b['g_end']}"
        rows.append([str(idx), str(b["size"]), str(b["start"]), leftmost, count, guaranteed])

    out.extend(build_table(headers, rows))
    out.append("")

    # --- Summary ------------------------------------------------------
    out.extend(section("SUMMARY"))
    if result["slack"] == 0:
        out.append("  Fill the entire line as laid out below (no ambiguity).")
    else:
        fills = [
            f"{b['g_start']}-{b['g_end']}"
            for b in result["blocks"]
            if b["g_start"] is not None
        ]
        if fills:
            out.append(f"  Fill cells: {', '.join(fills)}")
        else:
            out.append("  Nothing to fill yet - move to a lower-slack line.")

    pct = 100.0 * result["total_guaranteed"] / result["length"]
    out.append(
        f"  Guaranteed: {result['total_guaranteed']} of {result['length']} "
        f"cells ({pct:.0f}%)"
    )

    if result["slack"] > 0:
        unknown = [
            i
            for i in range(1, result["length"] + 1)
            if not any(
                b["g_start"] is not None and b["g_start"] <= i <= b["g_end"]
                for b in result["blocks"]
            )
        ]
        if unknown and len(unknown) <= 20:
            out.append(f"  Still ambiguous: {', '.join(str(u) for u in unknown)}")
        elif unknown:
            out.append(f"  Still ambiguous: {len(unknown)} cells")

    out.append("")

    # --- Picture ------------------------------------------------------
    legend = (
        f"'{colorize(FILLED, use_color)}' = guaranteed filled, "
        f"'{colorize(UNKNOWN, use_color)}' = unknown"
    )
    if result["slack"] == 0:
        legend += f", '{colorize(GAP, use_color)}' = forced empty"
    out.extend(section("LINE"))
    out.append(f"  {legend}")
    out.append(ruler(result["length"]))
    out.append(colorize(render_line(result), use_color))
    out.append("")

    return "\n".join(out)


QUIT_COMMANDS = {"q", "quit", "exit"}


# ---------------------------------------------------------------------------
# Batch/triage mode - a whole puzzle's rows and columns at once
# ---------------------------------------------------------------------------
#
# Input format:
#
#     SIZE: 80x80        (or just "80" for a square puzzle)
#
#     ROWS
#     1: 19,5,53
#     2: 5,2,27,6,11
#     12: 0             (0 = blank line)
#
#     COLUMNS
#     1: 46,6,17
#     ...
#
# Lines starting with '#' and blank lines are ignored. SIZE gives the
# default row length (width) and column length (height) for a square or
# rectangular grid - every ROWS entry is analyzed at length=width, every
# COLUMNS entry at length=height.

_CLUE_LINE_RE = re.compile(r"^(\d+)\s*:\s*(.+)$")


def parse_batch(text):
    """Parse a SIZE/ROWS/COLUMNS block into entries and errors.

    Returns (entries, errors):
      entries: list of dicts with keys kind, number, label, length,
               clues_raw, result (the analyze() dict)
      errors:  list of (label, message) tuples for lines that couldn't be
               parsed or didn't fit - the rest of the batch still proceeds.
    """
    width = height = None
    section = None  # "rows" or "columns" once a header is seen
    entries = []
    errors = []

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

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

        match = _CLUE_LINE_RE.match(line)
        if not match:
            errors.append((f"line {lineno}", f"Couldn't parse '{line}' (expected 'N: clues')"))
            continue

        number_str, clues_raw = match.groups()
        number = int(number_str)

        if section is None:
            errors.append(
                (f"line {lineno}", "Clue line appears before a ROWS or COLUMNS header")
            )
            continue

        label = f"{'Row' if section == 'rows' else 'Column'} {number}"
        length = width if section == "rows" else height

        if length is None:
            errors.append((label, "No SIZE declared - can't determine line length"))
            continue

        try:
            clues = parse_clues(clues_raw)
            result = analyze(length, clues)
        except LineError as exc:
            errors.append((label, str(exc)))
            continue

        entries.append(
            {
                "kind": section,
                "number": number,
                "label": label,
                "length": length,
                "clues_raw": clues_raw.strip(),
                "result": result,
            }
        )

    return entries, errors


def batch_sort_key(entry):
    """Fully-determined lines (blank, or slack 0) sort first; everything
    else by ascending slack. Ties break on row/column number for a stable,
    readable order."""
    r = entry["result"]
    fully_determined = r["is_blank"] or r["slack"] == 0
    tiebreak = (entry["kind"], entry["number"])
    if fully_determined:
        return (0, tiebreak)
    return (1, r["slack"], tiebreak)


def batch_fill_summary(entry):
    """Return (fill_text, resolved_count, resolved_pct) for one entry."""
    r = entry["result"]
    if r["is_blank"]:
        return "ALL EMPTY", r["length"], 100.0
    if r["slack"] == 0:
        return "ALL (fully determined)", r["length"], 100.0
    fills = [f"{b['g_start']}-{b['g_end']}" for b in r["blocks"] if b["g_start"] is not None]
    resolved = r["total_guaranteed"]
    pct = 100.0 * resolved / r["length"]
    return (", ".join(fills) if fills else "(none yet)"), resolved, pct


def format_batch_report(entries, errors, use_color=False, show_full=False):
    """Produce the full triage report: a priority-sorted summary table,
    an aggregate resolved-cell count, an error list, and optionally the
    full per-line breakdown for every solvable entry."""
    out = []
    total = len(entries) + len(errors)
    title = (
        f" BATCH TRIAGE - {total} line{'s' if total != 1 else ''} "
        f"({len(entries)} solvable, {len(errors)} error{'s' if len(errors) != 1 else ''}) "
    )
    out.append("=" * len(title))
    out.append(title)
    out.append("=" * len(title))
    out.append("")

    sorted_entries = sorted(entries, key=batch_sort_key)

    if entries:
        out.append("Sorted by priority: fully-determined lines first, then ascending slack.")
        out.append("")

        headers = ["#", "line", "len", "clues", "slack", "resolved", "%", "fill cells"]
        rows = []
        fully_determined_flags = []
        for rank, entry in enumerate(sorted_entries, start=1):
            r = entry["result"]
            is_fd = r["is_blank"] or r["slack"] == 0
            fully_determined_flags.append(is_fd)

            clues_display = "0 (blank)" if r["is_blank"] else ", ".join(str(c) for c in r["clues"])
            slack_display = "-" if r["is_blank"] else str(r["slack"])
            fill_text, resolved, pct = batch_fill_summary(entry)

            rows.append(
                [
                    str(rank),
                    entry["label"],
                    str(entry["length"]),
                    clues_display,
                    slack_display,
                    str(resolved),
                    f"{pct:.0f}%",
                    fill_text,
                ]
            )

        table_lines = build_table(headers, rows)
        out.append(table_lines[0])
        out.append(table_lines[1])
        for is_fd, row_line in zip(fully_determined_flags, table_lines[2:]):
            out.append(paint(row_line, _GREEN, use_color) if is_fd else row_line)
        out.append("")

        total_resolved = sum(
            entry["length"] if (entry["result"]["is_blank"] or entry["result"]["slack"] == 0)
            else entry["result"]["total_guaranteed"]
            for entry in entries
        )
        total_cells = sum(entry["length"] for entry in entries)
        pct_all = 100.0 * total_resolved / total_cells if total_cells else 0.0
        out.append(
            f"Total resolved across all lines: {total_resolved} of {total_cells} "
            f"cells ({pct_all:.0f}%)"
        )
        out.append("")

    if errors:
        out.extend(section(f"ERRORS ({len(errors)})"))
        for label, message in errors:
            out.append(paint(f"  {label}: {message}", _RED, use_color))
        out.append("")

    if show_full and entries:
        out.extend(section("FULL DETAIL (same priority order)"))
        out.append("")
        for entry in sorted_entries:
            out.append(format_report(entry["result"], use_color))

    return "\n".join(out)


def is_quit(text):
    return text.strip().lower() in QUIT_COMMANDS


def repl(use_color):
    """Interactive loop: keep solving lines, one after another, until the
    user quits - so a whole puzzle's worth of lines can be run without
    restarting the script each time."""
    print("Nonogram overlap solver - interactive mode")
    print("Enter a line length and its clues for each line (0 = blank line).")
    print("Type 'q' at either prompt to quit.\n")

    while True:
        try:
            length_raw = input("Line length: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not length_raw or is_quit(length_raw):
            return
        try:
            length = int(length_raw)
        except ValueError:
            print(f"Error: '{length_raw}' is not a valid line length.\n", file=sys.stderr)
            continue

        try:
            clues_raw = input("Clues (comma/space separated): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if is_quit(clues_raw):
            return

        try:
            clues = parse_clues(clues_raw)
            result = analyze(length, clues)
        except LineError as exc:
            print(f"Error: {exc}\n", file=sys.stderr)
            continue

        print()
        print(format_report(result, use_color))


def run_batch(batch_args, use_color):
    """Handle `--batch [file] [--full]`: read a whole puzzle's rows and
    columns at once, from a file or pasted stdin, and print the triage
    report."""
    full = False
    path = None
    for a in batch_args:
        if a in ("--full", "-f"):
            full = True
        elif path is None:
            path = a
        else:
            print(f"Error: unexpected argument '{a}'.", file=sys.stderr)
            return 1

    if path:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print(f"Error reading '{path}': {exc}", file=sys.stderr)
            return 1
    else:
        if sys.stdin.isatty():
            print(
                "Paste the puzzle's SIZE/ROWS/COLUMNS block, then press "
                "Ctrl-D (Ctrl-Z Enter on Windows):",
                file=sys.stderr,
            )
        text = sys.stdin.read()

    entries, errors = parse_batch(text)

    if not entries and not errors:
        print("Error: no rows or columns found in the input.", file=sys.stderr)
        return 1

    print()
    print(format_batch_report(entries, errors, use_color, full))
    return 0 if entries else 1


def main(argv):
    args = argv[1:]
    use_color = color_enabled()

    if args and args[0] in ("--batch", "-b", "batch"):
        return run_batch(args[1:], use_color)

    if not args:
        repl(use_color)
        return 0

    try:
        if len(args) >= 2:
            length = int(args[0])
            clues = parse_clues(" ".join(args[1:]))
        else:
            raise LineError(
                "Provide both a length and clues, e.g.:  "
                "nonogram_overlap.py 80 19,5,53"
            )
        result = analyze(length, clues)
    except LineError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError:
        print(f"Error: '{args[0]}' is not a valid line length.", file=sys.stderr)
        return 1

    print()
    print(format_report(result, use_color))
    return 0


def cli():
    """Console-script entry point (see pyproject.toml)."""
    sys.exit(main(sys.argv))


if __name__ == "__main__":
    cli()
