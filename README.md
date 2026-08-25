# nonogram-tool

A nonogram (picross / griddler) solving toolkit: a real constraint solver
underneath, not just a grid renderer — plus three interfaces (a REPL, a
full-screen TUI, and a local web UI) built on the exact same engine.

## Features

- **Line-level solving** — the classic slack/overlap technique, plus a
  general constraint solver that reasons over partially-marked lines
  (`nonogram_overlap`, `nonogram_linesolve`).
- **Live grid state** — a `Puzzle` holding every row/column's clue and
  current marks, with undo/redo, worklist-based propagation, tiered
  non-mutating hints, clue strikethrough (which clue numbers are fully
  pinned down), and eager contradiction detection on every manual mark
  (`nonogram_puzzle`).
- **A saved-puzzles library** — stable ids instead of file paths, with
  title/source metadata and a rough completion measure
  (`nonogram_library`).
- **Import from the `.non`/webpbn format** — monochrome puzzles only;
  multi-color puzzles are detected and rejected rather than misparsed
  (`nonogram_webpbn`).
- **Three interfaces sharing one engine**:
  - `nonogram-repl` — a `prompt_toolkit` REPL with history and command
    completion.
  - `nonogram-tui` — a full-screen `textual` app: click-free, keyboard-driven
    grid editing with live highlighting of whatever a solving action just
    forced.
  - `nonogram-web` — a small local HTTP server (stdlib only) plus one
    static HTML/JS page, for driving a puzzle from a browser.

## Installation

### Standalone binary (no Python required)

Download the `nonogram` binary for your OS from the
[Releases page](https://github.com/tylermac92/nonogram-tool/releases) — it
bundles Python and every dependency, so there's nothing to `pip install`.
Make it executable (`chmod +x nonogram` on Linux/macOS) and run it directly:

```bash
./nonogram overlap 80 19,5,53
./nonogram repl
./nonogram tui my-puzzle
./nonogram web my-puzzle
```

This one binary covers all four interfaces via subcommands (see
`./nonogram --help`). It's built by `.github/workflows/release.yml` with
PyInstaller from `packaging/nonogram.spec` whenever a `vX.Y.Z` tag is pushed.

### From source (pip)

Requires Python 3.9+.

```bash
git clone https://github.com/tylermac92/nonogram-tool.git
cd nonogram-tool
pip install -e .          # core engine + nonogram-overlap CLI only
pip install -e ".[repl]"  # + the REPL
pip install -e ".[tui]"   # + the TUI
pip install -e ".[all]"   # everything
```

The core engine (line solving, `Puzzle`, the library, `.non` import, and
`nonogram-overlap`'s batch/triage CLI) has **no third-party dependencies** —
only the REPL and TUI need `prompt_toolkit`/`textual`, so they're kept as
optional extras. Installing from source also gives you five console
scripts: `nonogram` (the unified dispatcher, same as the standalone binary)
plus `nonogram-overlap`/`nonogram-repl`/`nonogram-tui`/`nonogram-web` if you
prefer invoking one interface directly.

## Usage

The examples below use the `nonogram-*` console scripts (from a `pip
install`); if you're using the standalone binary instead, replace
`nonogram-overlap ...` with `nonogram overlap ...`, and likewise for
`repl`/`tui`/`web` — same arguments either way.

### Solve a single line

```bash
nonogram-overlap 80 19,5,53
```

### Triage a whole puzzle's worth of clues at once

```bash
nonogram-overlap --batch my_puzzle.txt
```

See `nonogram-overlap`'s own `--help`-equivalent (run it with no arguments
for the interactive line-by-line mode, or `--batch` with no file to paste a
`SIZE`/`ROWS`/`COLUMNS` block via stdin).

### Solve a live puzzle interactively

First get a puzzle into the library — either import one:

```python
from nonogram_tool.nonogram_webpbn import load_non
from nonogram_tool.nonogram_library import save_to_library

puzzle, metadata, errors = load_non("some_puzzle.non")
save_to_library(puzzle, id="my-puzzle", title=metadata.get("title"), source=metadata.get("catalogue"))
```

or hand-write one in the `SIZE`/`ROWS`/`COLUMNS`(/`GRID`) text format and
load it with `nonogram_tool.nonogram_puzzle.load_puzzle`, then
`save_to_library` it. Puzzles saved this way live under `puzzles/` (a
manifest-indexed library directory) relative to wherever you run the tools
from.

Then drive it with whichever interface you like:

```bash
nonogram-repl                    # start empty, `load <id>` from the library
nonogram-repl my-puzzle          # or load one straight away

nonogram-tui my-puzzle           # full-screen grid, arrow keys + space/x/c to mark

nonogram-web my-puzzle           # then open http://127.0.0.1:8765/
```

All three call the identical `Puzzle` methods underneath — `set_cell`,
`apply_line_solver`, `propagate`, `undo`/`redo`, the hint tiers, and
`solved_clue_indices` for strikethrough — so behavior (including eager
contradiction refusal on a bad manual mark) is consistent across all of
them.

### REPL command surface

`mark`, `solve`, `propagate`, `hint`, `undo`, `redo`, `save`, `load`,
`triage`, `help`; type `q`/`quit`/`exit` to leave. Run `help` inside the REPL
for exact syntax.

### TUI key bindings

Arrow keys move the cursor; `space`/`x`/`c` mark filled/empty/clear;
`ctrl+z`/`ctrl+y` undo/redo; `s` solves the cursor's row+column; `p`/`P`
propagate from the cursor or the whole grid; `h` shows a hint; `ctrl+s` saves
(only if launched with a library id). The footer lists these live.

### Web UI

Left-click fills a cell, right-click marks it empty, shift+click clears it.
Buttons cover propagate-all/undo/redo/save. The page re-fetches state after
every action and briefly highlights whatever cells just changed.

## Development

```bash
pip install -e ".[all]"
python -m unittest discover -s tests -v
```

Every module's own test file (`tests/test_nonogram_*.py`) is runnable on its
own too, e.g. `python -m unittest tests.test_nonogram_puzzle -v`.

### Building the standalone binary locally

```bash
pip install -e ".[all,build]"
pyinstaller packaging/nonogram.spec --distpath dist --workpath build/pyinstaller
./dist/nonogram overlap 5 3   # dist/nonogram.exe on Windows
```

PyInstaller doesn't cross-compile — this produces a binary for whichever OS
you run it on. `.github/workflows/release.yml` runs this on Linux, macOS,
and Windows runners and attaches all three to a GitHub Release whenever a
`vX.Y.Z` tag is pushed.

## Project layout

```
src/nonogram_tool/     the package (see its __init__.py for the module map)
tests/                 one test file per module, same layering
packaging/             PyInstaller spec for the standalone binary
```

## License

MIT — see [LICENSE](LICENSE).
