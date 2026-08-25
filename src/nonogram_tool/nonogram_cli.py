"""Unified `nonogram` command: one entry point dispatching to each
interface's own main(argv) - overlap, repl, tui, web.

Exists mainly for standalone binary distribution (see packaging/ and
.github/workflows/release.yml): a frozen executable bundles whatever
it imports regardless of which subcommand actually runs at any given
invocation, so one binary with subcommands is a better fit for end
users than four separate downloads each paying for their own bundled
Python interpreter. The four separate console scripts
(nonogram-overlap, nonogram-repl, nonogram-tui, nonogram-web) still
exist for a `pip install` - use whichever is more convenient there.

Each subcommand's module is imported lazily (only once selected), so
running `pip install nonogram-tool` (no extras) and using `nonogram
overlap ...` still works without prompt_toolkit/textual installed -
only `nonogram repl`/`nonogram tui` need their extra. This is invisible
to PyInstaller's static import analysis, though, so the frozen build's
spec lists all four submodules explicitly under hiddenimports rather
than relying on it noticing them here.
"""

import importlib
import sys

_SUBCOMMANDS = {
    "overlap": ("nonogram_tool.nonogram_overlap", "line solver / batch-triage CLI"),
    "repl": ("nonogram_tool.nonogram_repl", "interactive REPL driving a live Puzzle"),
    "tui": ("nonogram_tool.nonogram_tui", "full-screen TUI driving a live Puzzle"),
    "web": ("nonogram_tool.nonogram_web", "local web server + browser UI"),
}


def _usage():
    lines = ["Usage: nonogram <subcommand> [args...]", "", "Subcommands:"]
    for name, (_, desc) in _SUBCOMMANDS.items():
        lines.append(f"  {name:<8} {desc}")
    lines.append("")
    lines.append("Run `nonogram <subcommand>` with no further args for that")
    lines.append("subcommand's own usage.")
    return "\n".join(lines)


def main(argv):
    if len(argv) < 2:
        print(_usage(), file=sys.stderr)
        return 1
    if argv[1] in ("-h", "--help"):
        print(_usage())
        return 0

    name = argv[1]
    entry = _SUBCOMMANDS.get(name)
    if entry is None:
        print(f"Unknown subcommand: '{name}'\n", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        return 1

    module_name, _ = entry
    module = importlib.import_module(module_name)
    return module.main([f"nonogram {name}", *argv[2:]])


def cli():
    """Console-script / frozen-binary entry point."""
    sys.exit(main(sys.argv))


if __name__ == "__main__":
    cli()
