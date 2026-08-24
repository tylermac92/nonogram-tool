# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this
project doesn't yet promise strict semantic-versioning compatibility
guarantees pre-1.0.

## [0.1.0] - 2026-08-24

Initial packaged release. Everything below already existed as loose scripts
before this release restructured the project into an installable package
(`src/` layout, `pyproject.toml`, console scripts, extras); this entry
documents the feature set as of that packaging, not a single day's work.

### Added

- Line-level slack/overlap solver and reporting CLI (`nonogram-overlap`),
  including single-shot, interactive, and batch/triage modes.
- General constraint-based line solver reasoning over partially-marked
  lines (`nonogram_linesolve`).
- `Puzzle`: persistent grid state with undo/redo, save/load to text format.
- Worklist-based `propagate()` cascading deductions across rows/columns,
  returning the full set of forced cells for one combined undo step.
- Tiered, non-mutating hints (`has_any_move`, `find_move_lines`,
  `find_move_cells`, `explain_line`) and clue strikethrough
  (`solved_clue_indices`) — which physical clue numbers are fully pinned
  down, independent of how much of a line is known.
- Eager contradiction detection: `set_cell` refuses a manual mark that
  would make its row or column infeasible, rather than leaving it to be
  discovered later.
- Batch/triage report for a live `Puzzle` (`format_grid_triage_report`),
  ranking lines by unknown-cell count and pending-move status rather than
  the blank-line-only slack metric.
- A saved-puzzles library with stable ids, title/source/date metadata, and
  a rough completion measure (`nonogram_library`).
- Import from the `.non`/webpbn text format, scoped to monochrome puzzles
  (`nonogram_webpbn`).
- Three interfaces sharing the same `Puzzle` engine:
  - `nonogram-repl` — a `prompt_toolkit`-based REPL with persisted history
    and command completion.
  - `nonogram-tui` — a full-screen `textual` app with a custom grid widget,
    keyboard navigation, and live flash highlighting of forced cells.
  - `nonogram-web` — a local `http.server`-based JSON backend plus one
    static HTML/JS frontend.

### Packaging

- Restructured into a `src/nonogram_tool/` package installable via
  `pip install -e .`, with `repl`/`tui`/`all` optional extras so the
  dependency-free core doesn't require `prompt_toolkit`/`textual`.
- Added console scripts `nonogram-overlap`, `nonogram-repl`, `nonogram-tui`,
  `nonogram-web`.
