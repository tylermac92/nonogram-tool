"""Tests for the general line solver: nonogram_linesolve.py."""

import unittest

from nonogram_tool.nonogram_overlap import FILLED, GAP, UNKNOWN, analyze, render_line
from nonogram_tool.nonogram_linesolve import solve_line, LineContradiction, _is_feasible, find_solved_blocks


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


class TestFindSolvedBlocks(unittest.TestCase):
    def test_blank_clue_has_nothing_to_pin(self):
        self.assertEqual(find_solved_blocks([], [UNKNOWN] * 6), [])

    def test_slack_zero_pins_every_block(self):
        # Only one arrangement exists at all, so every block's start is
        # trivially the same in "every" (the one) valid arrangement.
        self.assertEqual(find_solved_blocks([3, 2], [UNKNOWN] * 6), [0, 1])

    def test_blank_line_with_slack_pins_nothing(self):
        self.assertEqual(find_solved_blocks([2, 2], [UNKNOWN] * 8), [])

    def test_a_filled_cell_can_pin_one_block_while_leaving_another_ambiguous(self):
        # clue [1, 1] in a length-7 line, with position 0 FILLED: that
        # cell can only belong to block 0 (there's no room for block 0
        # to fit before position 0 while leaving block 1 to cover it),
        # so block 0 is pinned at start 0. Block 1 could still start
        # anywhere from position 2 through 6, so it isn't pinned.
        known = [FILLED, UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN]
        self.assertEqual(find_solved_blocks([1, 1], known), [0])

    def test_a_filled_run_does_not_by_itself_say_which_block_it_is(self):
        # clue [2, 2] in a length-7 line, with only position 2 FILLED:
        # that cell could be covered by block 0 (e.g. spanning [1,3) or
        # [2,4)) or by block 1 (e.g. spanning [2,4) while block 0 sits
        # earlier) - genuinely ambiguous which clue index it belongs to,
        # so nothing is pinned yet even though a cell is known FILLED.
        known = [UNKNOWN, UNKNOWN, FILLED, UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN]
        self.assertEqual(find_solved_blocks([2, 2], known), [])

    def test_contradiction_raises(self):
        known = [FILLED, GAP, UNKNOWN, UNKNOWN, UNKNOWN]
        with self.assertRaises(LineContradiction):
            find_solved_blocks([3], known)


def _brute_force_pinned_blocks(clue, known):
    """Enumerate every arrangement consistent with known, and for each
    block collect the set of start positions it takes on across all of
    them. A block is pinned iff that set has exactly one element.
    Returns None if no consistent arrangement exists at all.
    """
    n = len(known)
    m = len(clue)
    starts_by_block = [set() for _ in range(m)]
    found_any = False
    for starts in _all_placements(clue, n):
        cells = _arrangement_cells(clue, starts, n)
        if all(known[i] == UNKNOWN or known[i] == cells[i] for i in range(n)):
            found_any = True
            for k, s in enumerate(starts):
                starts_by_block[k].add(s)
    if not found_any:
        return None
    return [k for k in range(m) if len(starts_by_block[k]) == 1]


PINNED_BLOCK_CASES = BRUTE_FORCE_CASES + [
    (7, [1, 1], [(0, FILLED)]),
    (7, [2, 2], [(2, FILLED)]),
    (6, [3, 2], []),
    (10, [4, 3], [(9, FILLED)]),
    (9, [2, 1, 2], [(4, GAP)]),
]


class TestFindSolvedBlocksBruteForceCrossCheck(unittest.TestCase):
    def test_matches_brute_force(self):
        for length, clue, knowns in PINNED_BLOCK_CASES:
            with self.subTest(length=length, clue=clue, knowns=knowns):
                known = [UNKNOWN] * length
                for i, state in knowns:
                    known[i] = state

                expected = _brute_force_pinned_blocks(clue, known)

                if expected is None:
                    with self.assertRaises(LineContradiction):
                        find_solved_blocks(clue, known)
                else:
                    self.assertEqual(sorted(find_solved_blocks(clue, known)), sorted(expected))


if __name__ == "__main__":
    unittest.main()
