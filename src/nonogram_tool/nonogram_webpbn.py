"""Import puzzles from the .non/webpbn text format into the
(row_clues, col_clues) shape Puzzle.__init__ already expects.

The field syntax below (quoted metadata values, bare width/height
integers, blank-line-separated rows/columns sections, "0" for a blank
line, an optional trailing goal bitstring) was checked against real
files pulled from webpbn.com's published archive - not assumed from
memory. e.g.:

    catalogue "webpbn.com #21"
    title "Slippery Conditions"
    by "Jan Wolter"
    copyright "&copy; Copyright 2004 by Jan Wolter"
    width 14
    height 25

    rows
    9
    1,1
    ...
    0
    ...

    columns
    2
    4,6
    ...

    goal "0001111111..."

Scope: monochrome (black/white) puzzles only. .non also supports
multi-color nonograms - a "color" key declaring a palette, plus runs
tagged with a color letter in the clue lines themselves (e.g.
"3b,1d,6b,4c" instead of "3,1,6,4"). Solving colored puzzles is a
genuinely different DP, not just a bigger one - this codebase's
solve_line only ever reasons about two cell states, FILLED/GAP - so a
colored file is reported as unsupported (via the same (puzzle_or_None,
errors) failure path as any other malformed file) rather than
misparsed into nonsense.

Scope: import is from a local file only, not fetch-by-id/URL from
webpbn.com - keeps this self-contained and independent of network
reliability. Revisit only if hand-downloading files becomes the actual
bottleneck.

parse_non()/load_non() return (puzzle_or_None, metadata, errors) - the
same (puzzle_or_None, errors) convention parse_puzzle()/load_puzzle()
already use for a malformed file, extended with one more value: a dict
of whatever string metadata keys the file's header defined (title, by,
copyright, catalogue, license). catalogue in particular is exactly a
"source/catalogue reference" - the puzzle library already has a field
for it - so a caller can pass metadata.get("catalogue") straight into
save_to_library(..., source=...) without this module needing to know
anything about the library.
"""

import re
from html import unescape

from .nonogram_overlap import LineError, parse_clues
from .nonogram_puzzle import Puzzle

_QUOTED_KEYS = ("title", "by", "copyright", "catalogue")
_KNOWN_KEYS = set(_QUOTED_KEYS) | {"license", "width", "height", "rows", "columns", "goal", "color"}

_COLORED_TOKEN_RE = re.compile(r"^\d+[A-Za-z]+$")


def _first_word(line):
    return line.split(None, 1)[0].lower()


def _quoted_value(line, key):
    """Value of `key "quoted value"` - None if key's argument isn't a
    quoted string at all (letting the caller report a clear error).
    """
    match = re.match(rf'^{re.escape(key)}\s+"(.*)"\s*$', line, re.IGNORECASE)
    return match.group(1) if match else None


def _looks_colored(text):
    """True if this file declares a color palette or tags any clue run
    with a color letter (e.g. "3b") - the signal this module uses to
    reject a puzzle as out of scope, without needing to fully parse the
    color extension it doesn't support.
    """
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        word = _first_word(line)
        if word == "color":
            return True
        if word in _KNOWN_KEYS:
            continue
        if any(_COLORED_TOKEN_RE.match(tok) for tok in re.split(r"[,\s]+", line) if tok):
            return True
    return False


def parse_non(text):
    """Parse .non/webpbn text into a Puzzle plus metadata. See the
    module docstring for the return shape and scope decisions.
    """
    if _looks_colored(text):
        return None, {}, [(
            "color",
            "This puzzle uses .non's multi-color extension, which isn't "
            "supported - only monochrome (black/white) puzzles can be "
            "imported.",
        )]

    metadata = {}
    width = height = None
    section = None
    row_clues = []
    col_clues = []
    errors = []

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        word = _first_word(line)

        if word in _QUOTED_KEYS:
            value = _quoted_value(line, word)
            if value is None:
                errors.append((f"line {lineno}", f"Expected a quoted value for '{word}'."))
            else:
                metadata[word] = unescape(value)
            continue

        if word == "license":
            parts = line.split(None, 1)
            metadata["license"] = parts[1].strip() if len(parts) == 2 else ""
            continue

        if word == "width" or word == "height":
            parts = line.split(None, 1)
            try:
                value = int(parts[1]) if len(parts) == 2 else None
                if value is None:
                    raise ValueError
            except ValueError:
                errors.append((f"line {lineno}", f"Invalid {word}: '{line}'."))
                continue
            if word == "width":
                width = value
            else:
                height = value
            continue

        if word == "rows":
            section = "rows"
            continue
        if word == "columns":
            section = "columns"
            continue
        if word == "goal":
            continue  # the solution bitstring - not needed for row_clues/col_clues

        if section not in ("rows", "columns"):
            continue  # unrecognized line outside any known section - .non
            # parsers are specified to ignore lines they don't recognize,
            # unlike this repo's own stricter native format.

        try:
            clue = parse_clues(line)
        except LineError as exc:
            errors.append((f"line {lineno}", str(exc)))
            continue

        (row_clues if section == "rows" else col_clues).append(clue)

    if width is None:
        errors.append(("width", "No width declared."))
    if height is None:
        errors.append(("height", "No height declared."))
    if errors:
        return None, metadata, errors

    if len(row_clues) != height:
        errors.append(("rows", f"Expected {height} row(s), got {len(row_clues)}."))
    if len(col_clues) != width:
        errors.append(("columns", f"Expected {width} column(s), got {len(col_clues)}."))
    if errors:
        return None, metadata, errors

    return Puzzle(row_clues=row_clues, col_clues=col_clues), metadata, []


def load_non(path):
    """Read a .non file. Returns (puzzle_or_None, metadata, errors),
    same convention as parse_non.
    """
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return parse_non(text)
