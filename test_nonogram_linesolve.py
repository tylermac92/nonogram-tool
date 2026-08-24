"""Tests for the general line solver: nonogram_linesolve.py."""

import unittest

from nonogram_overlap import FILLED, GAP, UNKNOWN, analyze, render_line
from nonogram_linesolve import solve_line, LineContradiction, _is_feasible


BLANK_LINE_CASES = [
    (5, [3]),
    (10, [3, 1]),
    (5, [2, 2]),
    (7, [1, 1, 1]),
    (6, [2, 2]),
    (1, [1]),
]


class TestBlankLineRegression(unittest.TestCase):
    def test_blank_line_matches_overlap_technique(self):
        for length, clue in BLANK_LINE_CASES:
            with self.subTest(length=length, clue=clue):
                expected = list(render_line(analyze(length, clue))[2:])
                actual = solve_line(clue, [UNKNOWN] * length)
                self.assertEqual(actual, expected)

    def test_blank_clue_line_is_all_gap(self):
        self.assertEqual(solve_line([], [UNKNOWN] * 6), [GAP] * 6)


class TestPartialStateDeduction(unittest.TestCase):
    def test_partial_state_single_filled_cell_solves_whole_line(self):
        known = [FILLED, UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN]
        self.assertEqual(solve_line([3], known), [FILLED, FILLED, FILLED, GAP, GAP])


class TestContradiction(unittest.TestCase):
    def test_contradiction_raises(self):
        known = [FILLED, GAP, UNKNOWN, UNKNOWN, UNKNOWN]
        with self.assertRaises(LineContradiction):
            solve_line([3], known)

    def test_is_feasible_directly(self):
        self.assertTrue(_is_feasible([3], [FILLED, UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN]))
        self.assertFalse(_is_feasible([3], [FILLED, GAP, UNKNOWN, UNKNOWN, UNKNOWN]))


def _all_placements(clue, n):
    m = len(clue)

    def recurse(block_idx, min_start):
        if block_idx == m:
            yield ()
            return
        size = clue[block_idx]
        for start in range(min_start, n - size + 1):
            for rest in recurse(block_idx + 1, start + size + 1):
                yield (start,) + rest

    yield from recurse(0, 0)


def _arrangement_cells(clue, starts, n):
    cells = [GAP] * n
    for size, start in zip(clue, starts):
        for k in range(start, start + size):
            cells[k] = FILLED
    return cells


def _brute_force_solve(clue, known):
    n = len(known)
    valid = []
    for starts in _all_placements(clue, n):
        cells = _arrangement_cells(clue, starts, n)
        if all(known[i] == UNKNOWN or known[i] == cells[i] for i in range(n)):
            valid.append(cells)

    if not valid:
        return None

    result = list(known)
    for i in range(n):
        if known[i] != UNKNOWN:
            continue
        values = {cells[i] for cells in valid}
        if len(values) == 1:
            result[i] = values.pop()
    return result


BRUTE_FORCE_CASES = [
    (5, [3], []),
    (5, [3], [(0, FILLED)]),
    (5, [3], [(0, FILLED), (1, GAP)]),
    (8, [2, 3], []),
    (8, [2, 3], [(4, FILLED)]),
    (8, [2, 3], [(0, GAP), (7, FILLED)]),
    (6, [1, 1, 1], []),
    (6, [1, 1, 1], [(2, GAP)]),
]


class TestBruteForceCrossCheck(unittest.TestCase):
    def test_matches_brute_force(self):
        for length, clue, knowns in BRUTE_FORCE_CASES:
            with self.subTest(length=length, clue=clue, knowns=knowns):
                known = [UNKNOWN] * length
                for i, state in knowns:
                    known[i] = state

                expected = _brute_force_solve(clue, known)

                if expected is None:
                    with self.assertRaises(LineContradiction):
                        solve_line(clue, known)
                else:
                    self.assertEqual(solve_line(clue, known), expected)


if __name__ == "__main__":
    unittest.main()
