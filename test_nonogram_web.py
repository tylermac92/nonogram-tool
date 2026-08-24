"""Tests for the local HTTP backend: nonogram_web.py.

Kept deliberately lighter than the REPL/TUI suites, matching this
piece's own "spec lightly, don't over-design" scope: real HTTP
requests against a live server (started on an ephemeral port in a
background thread) covering the JSON API's happy paths and error
paths, not exhaustive edge-case coverage. The frontend's JS is checked
only for valid syntax (via node --check, done manually during
development) - no headless-browser rendering tests, for the same
reason.
"""

import functools
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import nonogram_library
from nonogram_puzzle import Puzzle
from nonogram_web import NonogramHTTPServer

DIAMOND_ROWS = [[1], [3], [5], [3], [1]]
DIAMOND_COLS = [[1], [3], [5], [3], [1]]


class LiveServerTestCase(unittest.TestCase):
    """Starts a real NonogramHTTPServer on an ephemeral port for each
    test, wrapping a fresh Puzzle."""

    library_id = None
    puzzle_factory = staticmethod(lambda: Puzzle(row_clues=DIAMOND_ROWS, col_clues=DIAMOND_COLS))

    def setUp(self):
        self.puzzle = self.puzzle_factory()
        self.server = NonogramHTTPServer(("127.0.0.1", 0), self.puzzle, library_id=self.library_id)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def get(self, path):
        return json.loads(urlopen(self.base_url + path).read())

    def get_raw(self, path):
        return urlopen(self.base_url + path).read().decode("utf-8")

    def post(self, path, body):
        data = json.dumps(body).encode("utf-8")
        req = Request(
            self.base_url + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            resp = urlopen(req)
            return resp.status, json.loads(resp.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())


class TestStaticAndState(LiveServerTestCase):
    def test_index_is_served_at_root(self):
        html = self.get_raw("/")
        self.assertIn("<html", html)
        self.assertIn("board", html)

    def test_state_reflects_dimensions_and_clues(self):
        state = self.get("/api/state")
        self.assertEqual(state["width"], 5)
        self.assertEqual(state["height"], 5)
        self.assertEqual(state["row_clues"], DIAMOND_ROWS)
        self.assertEqual(state["col_clues"], DIAMOND_COLS)
        self.assertEqual(state["cells"], [["."] * 5] * 5)
        self.assertFalse(state["is_solved"])
        self.assertIsNone(state["library_id"])

    def test_unknown_path_is_404(self):
        with self.assertRaises(HTTPError) as ctx:
            urlopen(self.base_url + "/nope")
        self.assertEqual(ctx.exception.code, 404)


class TestMark(LiveServerTestCase):
    def test_mark_success_updates_state(self):
        status, body = self.post("/api/mark", {"row": 3, "col": 3, "state": "#"})
        self.assertEqual(status, 200)
        self.assertEqual(body["changes"], [[3, 3, "#"]])
        self.assertEqual(self.get("/api/state")["cells"][2][2], "#")

    def test_mark_contradiction_is_a_400_with_error(self):
        # (1,3) as GAP conflicts with row 1's clue [1] once row 1's
        # only block has nowhere else it could be - constructed via two
        # marks so the second one is the one that's actually refused.
        self.post("/api/mark", {"row": 1, "col": 3, "state": "#"})
        status, body = self.post("/api/mark", {"row": 1, "col": 3, "state": "x"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_mark_missing_field_is_a_400(self):
        status, body = self.post("/api/mark", {"row": 1, "col": 1})
        self.assertEqual(status, 400)
        self.assertIn("error", body)


class TestSolveAndPropagate(LiveServerTestCase):
    def test_solve_forces_a_slack_zero_line(self):
        status, body = self.post("/api/solve", {"kind": "row", "index": 3})
        self.assertEqual(status, 200)
        self.assertEqual(len(body["changes"]), 5)
        self.assertEqual(self.get("/api/state")["cells"][2], ["#"] * 5)

    def test_propagate_single_cell_solves_the_diamond(self):
        status, body = self.post("/api/propagate", {"row": 3, "col": 3})
        self.assertEqual(status, 200)
        self.assertTrue(self.get("/api/state")["is_solved"])

    def test_propagate_whole_grid_with_no_seed(self):
        status, body = self.post("/api/propagate", {})
        self.assertEqual(status, 200)
        self.assertTrue(self.get("/api/state")["is_solved"])

    def test_solved_line_is_reflected_in_row_solved(self):
        self.post("/api/solve", {"kind": "row", "index": 3})
        state = self.get("/api/state")
        self.assertEqual(state["row_solved"][2], [1])


class TestUndoRedo(LiveServerTestCase):
    def test_undo_reverts_a_mark(self):
        self.post("/api/mark", {"row": 1, "col": 1, "state": "#"})
        status, body = self.post("/api/undo", {})
        self.assertEqual(status, 200)
        self.assertEqual(len(body["changes"]), 1)
        self.assertEqual(self.get("/api/state")["cells"][0][0], ".")

    def test_undo_with_nothing_to_undo_returns_empty_changes(self):
        status, body = self.post("/api/undo", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["changes"], [])

    def test_redo_reapplies(self):
        self.post("/api/mark", {"row": 1, "col": 1, "state": "#"})
        self.post("/api/undo", {})
        status, body = self.post("/api/redo", {})
        self.assertEqual(status, 200)
        self.assertEqual(self.get("/api/state")["cells"][0][0], "#")


class TestSaveWithoutLibraryId(LiveServerTestCase):
    library_id = None

    def test_save_without_a_library_id_is_an_error(self):
        status, body = self.post("/api/save", {})
        self.assertEqual(status, 400)
        self.assertIn("error", body)


class TestSaveWithLibraryId(LiveServerTestCase):
    library_id = "diamond"

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        library_dir = Path(self._tmpdir.name) / "puzzles"
        patcher = patch(
            "nonogram_web.save_to_library",
            functools.partial(nonogram_library.save_to_library, library_dir=library_dir),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.library_dir = library_dir
        super().setUp()

    def test_state_reports_the_library_id(self):
        self.assertEqual(self.get("/api/state")["library_id"], "diamond")

    def test_save_writes_to_the_library(self):
        self.post("/api/mark", {"row": 3, "col": 3, "state": "#"})
        status, body = self.post("/api/save", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["saved_id"], "diamond")
        self.assertTrue((self.library_dir / "diamond.txt").exists())


if __name__ == "__main__":
    unittest.main()
