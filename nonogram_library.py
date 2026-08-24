"""A small saved-puzzles library, built on top of nonogram_puzzle.py's
text format: a directory of puzzle files plus one manifest indexing
them, so a puzzle can be referred to as a short stable id ("the 80x80")
instead of an exact file path.

Design choice - manifest file, not a METADATA text section:
metadata beyond clues+grid (title, source, date started, last touched,
a rough completion percentage) could have been layered onto the
existing SIZE/ROWS/COLUMNS/GRID format the same way GRID itself was
added later. A separate manifest was chosen instead, because
list_puzzles() needs to enumerate the whole library - name, size, rough
progress - without opening or parsing any individual puzzle file. A
manifest makes that an O(1) file read regardless of library size or how
big any one saved grid is; a per-file METADATA section would still mean
opening every file (even if you stop reading before its GRID body).
This also leaves nonogram_puzzle.py's already-tested text format and
save_puzzle()/load_puzzle() completely untouched - a puzzle file on
disk still means exactly what it meant before this module existed.

Saving to the library is always an explicit call (save_to_library()) -
nothing here or in Puzzle triggers it automatically. That's the same
lean taken on autosave back in Tier 1; revisit both together once a
real UI exists to make that call meaningfully.
"""

import json
import re
from datetime import date, datetime
from pathlib import Path

from nonogram_overlap import UNKNOWN
from nonogram_puzzle import load_puzzle, save_puzzle

DEFAULT_LIBRARY_DIR = Path("puzzles")
MANIFEST_FILENAME = "manifest.json"


def _manifest_path(library_dir):
    return Path(library_dir) / MANIFEST_FILENAME


def _load_manifest(library_dir):
    path = _manifest_path(library_dir)
    if not path.exists():
        return {"puzzles": {}}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_manifest(library_dir, manifest):
    path = _manifest_path(library_dir)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "puzzle"


def _generate_id(manifest, width, height, title):
    """A short, stable, human-referrable id: the title, slugified, if
    there is one, otherwise the puzzle's dimensions (e.g. "80x80") - so
    an untitled puzzle can still be called "the 80x80" rather than a
    file path. Disambiguated with a numeric suffix on collision.
    """
    base = _slugify(title) if title else f"{width}x{height}"
    if base not in manifest["puzzles"]:
        return base
    n = 2
    while f"{base}-{n}" in manifest["puzzles"]:
        n += 1
    return f"{base}-{n}"


def _progress_fraction(puzzle):
    """A rough, cheap "how far along" measure: the fraction of cells
    that are no longer UNKNOWN. Deliberately not is_solved()'s strict
    correctness check - a puzzle can be 100% marked and still wrong.
    """
    total = puzzle.width * puzzle.height
    if total == 0:
        return 1.0
    known = sum(
        1
        for r in range(1, puzzle.height + 1)
        for state in puzzle.get_row(r)
        if state != UNKNOWN
    )
    return known / total


def save_to_library(puzzle, library_dir=DEFAULT_LIBRARY_DIR, id=None, title=None, source=None):
    """Save a Puzzle into the library, creating a new entry or updating
    an existing one. Always explicit - see the module docstring.

    id is the library's stable per-puzzle handle, distinct from the
    backing filename. Omit it for a new puzzle to have one generated
    from title (or the puzzle's dimensions); pass an existing id to
    update that puzzle's saved progress in place.

    title/source default to whatever's already on file for an existing
    id, or a sensible default for a brand-new one. date_started is set
    once, on first save; last_touched updates on every save.

    Returns the id the puzzle was saved under.
    """
    library_dir = Path(library_dir)
    library_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(library_dir)

    existing = manifest["puzzles"].get(id) if id is not None else None
    if id is None:
        id = _generate_id(manifest, puzzle.width, puzzle.height, title)

    filename = f"{id}.txt"
    entry = {
        "filename": filename,
        "title": title if title is not None else (existing or {}).get("title", id),
        "source": source if source is not None else (existing or {}).get("source"),
        "width": puzzle.width,
        "height": puzzle.height,
        "progress": _progress_fraction(puzzle),
        "date_started": (existing or {}).get("date_started", date.today().isoformat()),
        "last_touched": datetime.now().isoformat(timespec="seconds"),
    }

    save_puzzle(puzzle, library_dir / filename)
    manifest["puzzles"][id] = entry
    _save_manifest(library_dir, manifest)
    return id


def open_puzzle(id, library_dir=DEFAULT_LIBRARY_DIR):
    """Load a Puzzle by its library id rather than a raw file path."""
    manifest = _load_manifest(library_dir)
    entry = manifest["puzzles"].get(id)
    if entry is None:
        raise KeyError(f"No puzzle {id!r} in the library at {library_dir}.")

    puzzle, errors = load_puzzle(Path(library_dir) / entry["filename"])
    if errors:
        raise ValueError(f"Puzzle {id!r} failed to load: {errors}")
    return puzzle


def list_puzzles(library_dir=DEFAULT_LIBRARY_DIR):
    """Enumerate what's in the library - id, title, size, and a rough
    completion fraction for each puzzle - read entirely from the
    manifest, without opening or parsing any individual puzzle file.
    Most recently touched first.
    """
    manifest = _load_manifest(library_dir)
    entries = [{"id": id, **entry} for id, entry in manifest["puzzles"].items()]
    entries.sort(key=lambda e: e["id"])
    entries.sort(key=lambda e: e["last_touched"], reverse=True)
    return entries
