# nonogram_linesolve.py
"""General line solver: given a clue and a line's current known state
(FILLED/GAP/UNKNOWN per cell), deduce every cell that's forced to the
same value in every valid arrangement.
"""

from .nonogram_overlap import FILLED, GAP, UNKNOWN


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


def find_solved_blocks(clue, known):
    """Return the 0-indexed positions of every clue block whose start is
    the same in every valid arrangement consistent with `known` - a
    block that's fully pinned down, not just one whose cells happen to
    already be FILLED.

    This is deliberately its own feasibility question, not something
    readable off solve_line()'s per-cell result: a run of FILLED cells
    doesn't by itself say which clue index it belongs to, especially
    before the line is fully solved. E.g. clue [2, 2] with only one
    FILLED cell known: that cell is forced to belong to *some* block,
    but which one - and where that block's other cell lands - may still
    be ambiguous. For block k, this asks: across every arrangement
    satisfying `clue` and consistent with `known`, is there exactly one
    feasible start position?

    Raises LineContradiction if `known` doesn't fit `clue` at all.
    """
    n = len(known)
    m = len(clue)

    if not _is_feasible(clue, known):
        raise LineContradiction(
            f"No arrangement of {clue} fits the current line state."
        )

    if m == 0:
        return []

    # reach[k]: cursor positions from which blocks[:k] could have been
    # validly arranged over cells [0, pos) - forward reachability only,
    # independent of whether block k onward can still complete from there.
    reach = [set() for _ in range(m + 1)]
    reach[0].add(0)
    for k in range(m):
        frontier = set(reach[k])
        for start in list(frontier):
            pos = start
            while pos < n and known[pos] != FILLED:
                pos += 1
                frontier.add(pos)
        reach[k] = frontier

        size = clue[k]
        for pos in reach[k]:
            end = pos + size
            if end > n or any(known[i] == GAP for i in range(pos, end)):
                continue
            if k + 1 < m:
                if end < n and known[end] != FILLED:
                    reach[k + 1].add(end + 1)
            else:
                reach[k + 1].add(end)

    def can_start_here(k, pos):
        """pos is already known reachable for block k (blocks before it
        can validly lead here) - can block k actually be placed at pos,
        *and* can blocks[k+1:] still complete the rest of the line from
        what's left? Reuses _is_feasible on the remaining clue/known
        suffix rather than re-deriving the same recursion."""
        size = clue[k]
        end = pos + size
        if end > n or any(known[i] == GAP for i in range(pos, end)):
            return False
        if k + 1 < m:
            if end >= n or known[end] == FILLED:
                return False
            return _is_feasible(clue[k + 1:], known[end + 1:])
        return _is_feasible(clue[k + 1:], known[end:])

    pinned = []
    for k in range(m):
        starts = [pos for pos in reach[k] if can_start_here(k, pos)]
        if len(starts) == 1:
            pinned.append(k)
    return pinned


if __name__ == "__main__":
    from .nonogram_overlap import analyze

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
