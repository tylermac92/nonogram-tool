"""Local HTTP backend for solving a Puzzle from a browser (JSON API).

Lowest priority of the tool's three interfaces (REPL, TUI, this one) -
explicitly "if you ever want" rather than committed scope, so this is
kept deliberately light: a handful of endpoints wrapping the same
Puzzle methods the REPL/TUI already call - mark, solve, propagate,
undo, redo, save - no framework (Python's stdlib http.server), no
auth, no websockets. The frontend just re-fetches state after every
action, which is plenty responsive for a single-user local tool with
nothing else writing to the same Puzzle concurrently.

Design choice - the server holds ONE Puzzle in memory for the
process's lifetime, matching the REPL/TUI's "one puzzle open at a
time" model, rather than reloading/saving from a library file on every
request. Saving is a separate, explicit action (POST /api/save),
consistent with every other interface's explicit-save stance.

Runs single-threaded (plain http.server.HTTPServer, not
ThreadingHTTPServer): requests are handled one at a time, which
sidesteps any need to lock the in-memory Puzzle against concurrent
mutation - a deliberate simplicity trade that's fine for a local,
single-user tool.

Not attempting feature parity with the TUI here (no clue-strikethrough
detail beyond what's needed to render it, no hint tiers exposed) -
this shares the same underlying Puzzle methods, so extending it is
mostly wiring, not new logic; left for whenever this piece actually
gets built out further.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .nonogram_linesolve import LineContradiction
from .nonogram_library import open_puzzle, save_to_library

STATIC_HTML_PATH = Path(__file__).parent / "nonogram_web.html"
DEFAULT_PORT = 8765


def _safe_solved_indices(puzzle, kind, index):
    """puzzle.solved_clue_indices(), but a contradictory line just
    means "nothing to strike through yet" for display - not duplicated
    from nonogram_tui.py's identical helper, since importing that
    module here would pull in textual/rich for a server that otherwise
    needs neither."""
    try:
        return sorted(puzzle.solved_clue_indices(kind, index))
    except LineContradiction:
        return []


def puzzle_state(puzzle, library_id):
    """The full JSON-able snapshot the frontend needs to draw the
    board: dimensions, clues, every cell's current mark, and which
    clue blocks are pinned (for strikethrough) per line.
    """
    return {
        "width": puzzle.width,
        "height": puzzle.height,
        "row_clues": puzzle.row_clues,
        "col_clues": puzzle.col_clues,
        "cells": [puzzle.get_row(r) for r in range(1, puzzle.height + 1)],
        "row_solved": [_safe_solved_indices(puzzle, "row", r) for r in range(1, puzzle.height + 1)],
        "col_solved": [_safe_solved_indices(puzzle, "col", c) for c in range(1, puzzle.width + 1)],
        "is_solved": puzzle.is_solved(),
        "library_id": library_id,
    }


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, text):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_html(STATIC_HTML_PATH.read_text(encoding="utf-8"))
        elif path == "/api/state":
            self._send_json(puzzle_state(self.server.puzzle, self.server.library_id))
        else:
            self._send_json({"error": f"Not found: {path}"}, status=404)

    def do_POST(self):
        path = urlparse(self.path).path
        puzzle = self.server.puzzle

        try:
            body = self._read_json_body()
        except ValueError:
            self._send_json({"error": "Invalid JSON body."}, status=400)
            return

        try:
            if path == "/api/mark":
                row, col, state = body["row"], body["col"], body["state"]
                puzzle.set_cell(row, col, state)
                self._send_json({"changes": [[row, col, state]]})
            elif path == "/api/solve":
                changes = puzzle.apply_line_solver(body["kind"], body["index"])
                self._send_json({"changes": changes})
            elif path == "/api/propagate":
                if body.get("row") is not None and body.get("col") is not None:
                    seeds = [(body["row"], body["col"])]
                else:
                    seeds = [(r, 1) for r in range(1, puzzle.height + 1)]
                    seeds += [(1, c) for c in range(1, puzzle.width + 1)]
                changes = puzzle.propagate(seeds)
                self._send_json({"changes": changes})
            elif path == "/api/undo":
                self._send_json({"changes": puzzle.undo()})
            elif path == "/api/redo":
                self._send_json({"changes": puzzle.redo()})
            elif path == "/api/save":
                if self.server.library_id is None:
                    self._send_json({"error": "No library id for this puzzle."}, status=400)
                else:
                    save_to_library(puzzle, id=self.server.library_id)
                    self._send_json({"saved_id": self.server.library_id})
            else:
                self._send_json({"error": f"Not found: {path}"}, status=404)
        except LineContradiction as exc:
            self._send_json({"error": str(exc)}, status=400)
        except (KeyError, ValueError, TypeError) as exc:
            self._send_json({"error": str(exc)}, status=400)

    def log_message(self, format, *args):
        pass  # a small local server doesn't need access logs on stdout


class NonogramHTTPServer(HTTPServer):
    """Carries the one live Puzzle (and its library id, if any) for the
    process's lifetime - see the module docstring for why in-memory."""

    def __init__(self, server_address, puzzle, library_id=None):
        super().__init__(server_address, Handler)
        self.puzzle = puzzle
        self.library_id = library_id


def main(argv):
    if len(argv) < 2:
        print(f"Usage: {argv[0]} <library-id> [port]", file=sys.stderr)
        return 1

    library_id = argv[1]
    port = int(argv[2]) if len(argv) > 2 else DEFAULT_PORT

    try:
        puzzle = open_puzzle(library_id)
    except (KeyError, ValueError) as exc:
        print(f"Error loading '{library_id}': {exc}", file=sys.stderr)
        return 1

    server = NonogramHTTPServer(("127.0.0.1", port), puzzle, library_id=library_id)
    print(f"Serving '{library_id}' at http://127.0.0.1:{port}/ (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cli():
    """Console-script entry point (see pyproject.toml)."""
    sys.exit(main(sys.argv))


if __name__ == "__main__":
    cli()
