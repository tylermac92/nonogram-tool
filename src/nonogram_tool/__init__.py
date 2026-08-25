"""nonogram-tool: a nonogram (picross) solving toolkit.

Layered modules, each built on the ones before it:
  nonogram_overlap    - line-level slack/overlap solver, CLI, formatting helpers
  nonogram_linesolve  - general line solver (constraint feasibility over partial state)
  nonogram_puzzle     - persistent grid state, propagation, hints, triage
  nonogram_library    - a saved-puzzles library with stable ids
  nonogram_webpbn     - import puzzles from the .non/webpbn format
  nonogram_repl       - a prompt_toolkit REPL driving a live Puzzle
  nonogram_tui        - a full-screen textual TUI driving a live Puzzle
  nonogram_web        - a local HTTP backend + static HTML frontend

prompt_toolkit and textual are optional - install with the `repl` and
`tui` extras (or `all`) respectively; the rest of the package has no
third-party dependencies.
"""

__version__ = "0.1.0"
