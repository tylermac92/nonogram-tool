"""Tests for the saved-puzzles library: nonogram_library.py."""

import tempfile
import unittest
from pathlib import Path

from nonogram_overlap import FILLED, GAP, UNKNOWN
from nonogram_puzzle import Puzzle, load_puzzle
from nonogram_library import (
    save_to_library,
    open_puzzle,
    list_puzzles,
    _load_manifest,
    _save_manifest,
)


class LibraryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.library_dir = Path(self._tmpdir.name) / "puzzles"


class TestSaveToLibrary(LibraryTestCase):
    def test_creates_the_library_directory(self):
        self.assertFalse(self.library_dir.exists())
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        save_to_library(puzzle, library_dir=self.library_dir)
        self.assertTrue(self.library_dir.is_dir())

    def test_writes_a_loadable_puzzle_file(self):
        puzzle = Puzzle(row_clues=[[1, 1]], col_clues=[[1]] * 7)
        id = save_to_library(puzzle, library_dir=self.library_dir, title="Test")
        loaded, errors = load_puzzle(self.library_dir / f"{id}.txt")
        self.assertEqual(errors, [])
        self.assertEqual(loaded.row_clues, puzzle.row_clues)
        self.assertEqual(loaded.col_clues, puzzle.col_clues)

    def test_id_defaults_to_dimensions_when_no_title(self):
        puzzle = Puzzle(row_clues=[[1], [1]], col_clues=[[1], [1], [1]])
        id = save_to_library(puzzle, library_dir=self.library_dir)
        self.assertEqual(id, "3x2")  # width x height

    def test_id_defaults_to_slugified_title(self):
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        id = save_to_library(puzzle, library_dir=self.library_dir, title="Plus Sign!")
        self.assertEqual(id, "plus-sign")

    def test_id_collision_gets_a_disambiguating_suffix(self):
        p1 = Puzzle(row_clues=[[1]], col_clues=[[1]])
        p2 = Puzzle(row_clues=[[1]], col_clues=[[1]])
        id1 = save_to_library(p1, library_dir=self.library_dir)
        id2 = save_to_library(p2, library_dir=self.library_dir)
        self.assertEqual(id1, "1x1")
        self.assertEqual(id2, "1x1-2")

    def test_reusing_an_id_updates_that_entry_in_place(self):
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        id = save_to_library(puzzle, library_dir=self.library_dir, title="Original")
        manifest_before = _load_manifest(self.library_dir)
        self.assertEqual(len(manifest_before["puzzles"]), 1)

        puzzle.set_cell(1, 1, FILLED)
        same_id = save_to_library(puzzle, library_dir=self.library_dir, id=id)

        self.assertEqual(same_id, id)
        manifest_after = _load_manifest(self.library_dir)
        self.assertEqual(len(manifest_after["puzzles"]), 1)  # still one entry, not two
        self.assertEqual(manifest_after["puzzles"][id]["progress"], 1.0)

    def test_date_started_is_preserved_across_updates(self):
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        id = save_to_library(puzzle, library_dir=self.library_dir)

        # Backdate it directly, to prove a later save preserves the
        # original value instead of resetting to today.
        manifest = _load_manifest(self.library_dir)
        manifest["puzzles"][id]["date_started"] = "2020-01-01"
        _save_manifest(self.library_dir, manifest)

        save_to_library(puzzle, library_dir=self.library_dir, id=id)
        reloaded = _load_manifest(self.library_dir)
        self.assertEqual(reloaded["puzzles"][id]["date_started"], "2020-01-01")

    def test_title_and_source_are_preserved_when_omitted_on_update(self):
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        id = save_to_library(
            puzzle, library_dir=self.library_dir, title="Keep Me", source="Cheatsheet #3"
        )

        save_to_library(puzzle, library_dir=self.library_dir, id=id)  # no title/source passed

        manifest = _load_manifest(self.library_dir)
        self.assertEqual(manifest["puzzles"][id]["title"], "Keep Me")
        self.assertEqual(manifest["puzzles"][id]["source"], "Cheatsheet #3")

    def test_title_and_source_are_overwritten_when_provided_on_update(self):
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        id = save_to_library(puzzle, library_dir=self.library_dir, title="Old", source="Old source")

        save_to_library(puzzle, library_dir=self.library_dir, id=id, title="New", source="New source")

        manifest = _load_manifest(self.library_dir)
        self.assertEqual(manifest["puzzles"][id]["title"], "New")
        self.assertEqual(manifest["puzzles"][id]["source"], "New source")

    def test_progress_is_the_fraction_of_non_unknown_cells(self):
        puzzle = Puzzle(row_clues=[[1], [1]], col_clues=[[1], [1]])  # 2x2 grid
        id = save_to_library(puzzle, library_dir=self.library_dir)
        manifest = _load_manifest(self.library_dir)
        self.assertEqual(manifest["puzzles"][id]["progress"], 0.0)

        puzzle.set_cell(1, 1, FILLED)
        save_to_library(puzzle, library_dir=self.library_dir, id=id)
        manifest = _load_manifest(self.library_dir)
        self.assertAlmostEqual(manifest["puzzles"][id]["progress"], 0.25)  # 1 of 4 cells

        # With (1,1) FILLED already, each row/col's single-block clue
        # forces the rest of the grid: (1,2) and (2,1) GAP, (2,2) FILLED.
        puzzle.set_cell(1, 2, GAP)
        puzzle.set_cell(2, 1, GAP)
        puzzle.set_cell(2, 2, FILLED)
        save_to_library(puzzle, library_dir=self.library_dir, id=id)
        manifest = _load_manifest(self.library_dir)
        self.assertEqual(manifest["puzzles"][id]["progress"], 1.0)


class TestOpenPuzzle(LibraryTestCase):
    def test_open_returns_an_equivalent_puzzle(self):
        puzzle = Puzzle(row_clues=[[1], [1]], col_clues=[[2]])
        puzzle.set_cell(1, 1, FILLED)
        id = save_to_library(puzzle, library_dir=self.library_dir)

        reopened = open_puzzle(id, library_dir=self.library_dir)
        self.assertEqual(reopened.row_clues, puzzle.row_clues)
        self.assertEqual(reopened.col_clues, puzzle.col_clues)
        self.assertEqual(reopened.get_row(1), puzzle.get_row(1))

    def test_open_unknown_id_raises_key_error(self):
        with self.assertRaises(KeyError):
            open_puzzle("no-such-puzzle", library_dir=self.library_dir)

    def test_open_reflects_the_most_recently_saved_progress(self):
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        id = save_to_library(puzzle, library_dir=self.library_dir)

        puzzle.set_cell(1, 1, FILLED)
        save_to_library(puzzle, library_dir=self.library_dir, id=id)

        reopened = open_puzzle(id, library_dir=self.library_dir)
        self.assertEqual(reopened.get_cell(1, 1), FILLED)


class TestListPuzzles(LibraryTestCase):
    def test_empty_library_lists_nothing(self):
        self.assertEqual(list_puzzles(library_dir=self.library_dir), [])

    def test_lists_every_saved_puzzle_with_expected_fields(self):
        p1 = Puzzle(row_clues=[[1]], col_clues=[[1]])
        p2 = Puzzle(row_clues=[[1], [1]], col_clues=[[1], [1]])
        save_to_library(p1, library_dir=self.library_dir, title="First", source="Book A")
        save_to_library(p2, library_dir=self.library_dir, title="Second")

        by_title = {e["title"]: e for e in list_puzzles(library_dir=self.library_dir)}
        self.assertEqual(set(by_title), {"First", "Second"})
        self.assertEqual(by_title["First"]["source"], "Book A")
        self.assertEqual(by_title["First"]["width"], 1)
        self.assertEqual(by_title["First"]["height"], 1)
        self.assertEqual(by_title["Second"]["width"], 2)
        self.assertEqual(by_title["Second"]["height"], 2)
        self.assertIn("progress", by_title["First"])
        self.assertIn("date_started", by_title["First"])
        self.assertIn("last_touched", by_title["First"])

    def test_does_not_open_or_parse_any_puzzle_file(self):
        # Save one real puzzle, then corrupt its backing file - if
        # list_puzzles() ever touched the file, this would blow up.
        puzzle = Puzzle(row_clues=[[1]], col_clues=[[1]])
        id = save_to_library(puzzle, library_dir=self.library_dir, title="Fragile")
        (self.library_dir / f"{id}.txt").write_text("not a valid puzzle file at all\n")

        entries = list_puzzles(library_dir=self.library_dir)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Fragile")

    def test_sorted_most_recently_touched_first(self):
        # Build the manifest directly with explicit timestamps, since
        # real saves in a fast test run can land in the same second.
        manifest = {
            "puzzles": {
                "older": {
                    "filename": "older.txt",
                    "title": "Older",
                    "source": None,
                    "width": 1,
                    "height": 1,
                    "progress": 0.0,
                    "date_started": "2020-01-01",
                    "last_touched": "2020-01-01T00:00:00",
                },
                "newer": {
                    "filename": "newer.txt",
                    "title": "Newer",
                    "source": None,
                    "width": 1,
                    "height": 1,
                    "progress": 0.0,
                    "date_started": "2021-01-01",
                    "last_touched": "2021-01-01T00:00:00",
                },
            }
        }
        self.library_dir.mkdir(parents=True)
        _save_manifest(self.library_dir, manifest)

        entries = list_puzzles(library_dir=self.library_dir)
        self.assertEqual([e["id"] for e in entries], ["newer", "older"])


if __name__ == "__main__":
    unittest.main()
