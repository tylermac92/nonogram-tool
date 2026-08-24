# nonogram_linesolve.py
"""General line solver: given a clue and a line's current known state
(FILLED/GAP/UNKNOWN per cell), deduce every cell that's forced to the
same value in every valid arrangement.
"""

from nonogram_overlap import FILLED, GAP, UNKNOWN


class LineContradiction(ValueError):
    """Raised when a line's already-known cells can't satisfy its clue,
    no matter how the rest of the line is filled in.
    """


def _is_feasible(clue, known):
    """True if some arrangement of clue's blocks fits known."""
    n = len(known)
    m = len(clue)
    memo = {}

    def can_fill(pos, block_idx):
        key = (pos, block_idx)
        if key in memo:
            return memo[key]

        if block_idx == m:
            # No blocks left - every remaining cell must be non-FILLED.
            result = all(known[k] != FILLED for k in range(pos, n))
            memo[key] = result
            return result

        if pos >= n:
            # Ran out of cells but blocks remain.
            memo[key] = False
            return False

        result = False

        # Option 1: treat the cell at pos as empty and move on.
        if known[pos] != FILLED and can_fill(pos + 1, block_idx):
            result = True

        # Option 2: place the current block starting at pos.
        if not result:
            size = clue[block_idx]
            end = pos + size
            if end <= n and all(known[k] != GAP for k in range(pos, end)):
                if block_idx + 1 < m:
                    # More blocks follow - a gap cell must separate them.
                    if end < n and known[end] != FILLED and can_fill(end + 1, block_idx + 1):
                        result = True
                else:
                    if can_fill(end, block_idx + 1):
                        result = True

        memo[key] = result
        return result

    return can_fill(0, 0)


def solve_line(clue, known):
    """Given a clue and the line's current known state (FILLED/GAP/
    UNKNOWN per cell), return a new list with every cell that's forced
    to the same value across every valid arrangement. Cells that could
    still go either way stay UNKNOWN.
    """
    if not _is_feasible(clue, known):
        raise LineContradiction(
            f"No arrangement of {clue} fits the current line state."
        )

    result = list(known)
    for i, state in enumerate(known):
        if state != UNKNOWN:
            continue  # already known - nothing to deduce

        trial = list(known)
        trial[i] = FILLED
        filled_possible = _is_feasible(clue, trial)

        trial[i] = GAP
        gap_possible = _is_feasible(clue, trial)

        if filled_possible and not gap_possible:
            result[i] = FILLED
        elif gap_possible and not filled_possible:
            result[i] = GAP
        # both possible -> still ambiguous, leave UNKNOWN
        # (both impossible can't happen - the original `known`, with this
        # cell still UNKNOWN, was already confirmed feasible above)

    return result


if __name__ == "__main__":
    from nonogram_overlap import analyze

    # Blank-line regression check: with nothing known, solve_line should
    # match what analyze()'s overlap technique already gives you.
    clue, length = [3, 1], 10
    blank = [UNKNOWN] * length
    solved = solve_line(clue, blank)
    print("blank-line result:", "".join(solved))
    print("analyze() slack:  ", analyze(length, clue)["slack"])

    # The interesting case: one known FILLED cell the overlap technique
    # alone would never have seen.
    known = [FILLED, UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN]
    solved = solve_line([3], known)
    print("partial-state result:", "".join(solved))
    # Expect FILLED,FILLED,FILLED,GAP,GAP - a single size-3 block is the
    # only way to cover a filled cell at position 0, which fully solves
    # the line even though the blank-line overlap here gives you nothing
    # (slack=2 >= block size, so analyze() alone wouldn't force any cell).
