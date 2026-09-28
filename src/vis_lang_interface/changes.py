"""Counting the lines an edit added and removed.

Formatters rewrite text, and a `FormatResult` reports how much of it changed in
`lines_added` and `lines_removed`. Every language extension counts them with
`line_changes`, so they all agree with each other and with `git diff --minimal`.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from itertools import repeat

_CHUNK = 64
"""Lines compared at once while skipping the ends two texts share."""

_LINES_PER_STEP = 1800
"""Lines of the longer side that add one step to a bit-parallel row, as measured."""

_MOST_STEPS = 2_000_000
"""Steps, about half a second, an exact count may take before anchoring takes over."""

_MOST_MASK_BITS = 1 << 28
"""Bits, 32 MiB, the masks of repeated lines may hold in one exact count."""

_MOST_PAIRS = 1_000_000
"""Pairs of equal lines, about half a second, a count past the step budget may follow."""


def line_changes(before: str, after: str) -> tuple[int, int]:
    """Lines `after` adds to and removes from `before`, as `(added, removed)`.

    A changed line counts once in each, and a line counts with its newline, so a
    last line that only gains or loses one counts as removed and added. The
    counts are the smallest any line diff gives, the numbers `git diff --minimal
    --numstat` reports. A changed region too large to count exactly in about half
    a second, tens of thousands of lines, is matched through the lines that
    repeat least, as patience and histogram diffs do; its counts may then exceed
    the fewest, never fall below them.
    """
    if before == after:
        return 0, 0
    old, new = _lines(before), _lines(after)
    kept = _kept(old, new)
    return len(new) - kept, len(old) - kept


def _lines(text):
    """The lines of `text`; a last line without a newline stays a 1-tuple.

    `str.split` breaks only at newlines, unlike `str.splitlines`, so a carriage
    return or form feed stays part of its line, as in git.
    """
    lines = text.split("\n")
    last = lines.pop()
    if last:
        lines.append((last,))
    return lines


def _kept(old, new):
    """Length of a common subsequence of `old` and `new`, longest within the budget."""
    old, new, kept = _reduced(old, new)
    if not old or not new:
        return kept
    found = _exact(old, new, _MOST_STEPS)
    if found is None:
        found = _anchored(old, new)
    return kept + found


def _reduced(old, new):
    """`old` and `new` less every line a longest common subsequence settles alone.

    Lines shared at both ends are kept, and a line only one side holds is not;
    dropping those often exposes more shared ends. Returns both remainders and
    the number of lines kept at the ends.
    """
    old, new, kept = _without_shared_ends(old, new)
    if not old or not new:
        return old, new, kept
    left, right = set(old), set(new)
    shared = left & right
    if not shared:
        return [], [], kept
    if len(shared) < len(left):
        old = list(filter(shared.__contains__, old))
    if len(shared) < len(right):
        new = list(filter(shared.__contains__, new))
    old, new, ends = _without_shared_ends(old, new)
    return old, new, kept + ends


def _without_shared_ends(old, new):
    """`old` and `new` less the lines they share at both ends, and how many those were."""
    n, m = len(old), len(new)
    top = min(n, m)
    head = 0
    while (
        head + _CHUNK <= top and old[head : head + _CHUNK] == new[head : head + _CHUNK]
    ):
        head += _CHUNK
    while head < top and old[head] == new[head]:
        head += 1
    top -= head
    tail = 0
    while (
        tail + _CHUNK <= top
        and old[n - tail - _CHUNK : n - tail] == new[m - tail - _CHUNK : m - tail]
    ):
        tail += _CHUNK
    while tail < top and old[n - tail - 1] == new[m - tail - 1]:
        tail += 1
    if not head and not tail:
        return old, new, 0
    return old[head : n - tail], new[head : m - tail], head + tail


def _steps(old, new):
    """What a bit-parallel count of `old` against `new` costs, in steps."""
    shorter, longer = sorted((len(old), len(new)))
    return shorter * (1 + longer // _LINES_PER_STEP)


def _exact(old, new, budget):
    """Longest common subsequence length within `budget` steps, or None.

    Myers' search goes first while the lengths allow few differences, since it
    settles scattered changes in a long file at once; bit-parallel rows take
    over when it runs long, because their cost does not grow with the changes.
    """
    steps = _steps(old, new)
    most = min(steps, budget) // 2
    gap = abs(len(old) - len(new))
    if (gap + 1) * (gap + 2) // 2 <= most:
        found = _myers(old, new, most)
        if found is not None:
            return found
    if steps <= budget:
        return _bit_parallel(old, new)
    return None


def _myers(old, new, budget):
    """Common subsequence length by Myers' greedy search, or None past `budget`.

    It explores one more difference per round, costing O((N+M)·D). A round
    costs one step per diagonal, plus an eighth of one per line a snake follows.
    """
    n, m = len(old), len(new)
    limit = min(n + m, int((2 * budget) ** 0.5) + 1)
    offset = limit + 1
    reach = [0] * (2 * limit + 3)
    walked = 0
    for d in range(limit + 1):
        low, high = offset - d, offset + d
        for k in range(low, high + 1, 2):
            if k == low or (k != high and reach[k - 1] < reach[k + 1]):
                x = reach[k + 1]
            else:
                x = reach[k - 1] + 1
            y = x - k + offset
            start = x
            while x < n and y < m and old[x] == new[y]:
                x += 1
                y += 1
            if x >= n and y >= m:
                return (n + m - d) // 2
            reach[k] = x
            walked += x - start
        if (d + 1) * (d + 2) // 2 + walked // 8 > budget:
            return None
    return None


def _bit_parallel(old, new):
    """Common subsequence length by bit-parallel rows (Hyyrö 2004), or None.

    One integer holds a bit per line of the longer side, and each line of the
    shorter side updates it with four big-integer operations, so Python loops
    once per line while the carries run in C: O(N·M/w), whatever the changes. A
    line met once keeps its position and becomes a mask only when used, so the
    masks stay small unless many lines repeat; past `_MOST_MASK_BITS` it gives up.
    """
    if len(old) > len(new):
        old, new = new, old
    size = len(new)
    where = {}
    repeated = 0
    for j, line in enumerate(new):
        seen = where.get(line)
        if seen is None:
            where[line] = ~j
        elif seen < 0:
            repeated += 1
            if repeated * size > _MOST_MASK_BITS:
                return None
            where[line] = 1 << ~seen | 1 << j
        else:
            where[line] = seen | 1 << j
    full = (1 << size) - 1
    row = full
    for match in map(where.get, old, repeat(0)):
        if match < 0:
            match = 1 << ~match
        match &= row
        row = ((row + match) | (row - match)) & full
    return size - row.bit_count()


def _anchored(old, new):
    """A common subsequence length through lines each side holds once.

    Patience diff anchors the same way: those lines, in the longest run that
    keeps their order, split both sides into gaps counted exactly while the
    budget lasts. A gap past it follows only the lines that repeat least, so
    the length stays that of a real common subsequence.
    """
    counts_old, counts_new = Counter(old), Counter(new)
    where = {line: j for j, line in enumerate(new) if counts_new[line] == 1}
    pairs = [
        (i, where[line])
        for i, line in enumerate(old)
        if counts_old[line] == 1 and line in where
    ]
    tails, ends, before = [], [], [None] * len(pairs)
    for p, (_, j) in enumerate(pairs):
        k = bisect_left(tails, j)
        if k == len(tails):
            tails.append(j)
            ends.append(p)
        else:
            tails[k] = j
            ends[k] = p
        before[p] = ends[k - 1] if k else None
    anchors = []
    p = ends[-1] if ends else None
    while p is not None:
        anchors.append(pairs[p])
        p = before[p]
    anchors.reverse()
    budget, most = _MOST_STEPS, _MOST_PAIRS
    kept = len(anchors)
    i0 = j0 = 0
    for i, j in [*anchors, (len(old), len(new))]:
        gap_old, gap_new, ends_kept = _reduced(old[i0:i], new[j0:j])
        kept += ends_kept
        if gap_old and gap_new:
            found = _exact(gap_old, gap_new, budget) if anchors else None
            budget -= _steps(gap_old, gap_new)
            if found is None:
                found, followed = _sparse(gap_old, gap_new, most)
                most -= followed
            kept += found
        i0, j0 = i + 1, j + 1
    return kept


def _sparse(old, new, most):
    """A common subsequence length through the lines that repeat least.

    Hunt and Szymanski's count follows every pair of equal lines, in time
    O(P log N) for P pairs, so it takes the lines with the fewest pairs while
    their total stays within `most`. Leaving the others out keeps it a real
    common subsequence. Returns its length and the pairs it followed.
    """
    counts_old, counts_new = Counter(old), Counter(new)
    shared = sorted(
        counts_old.keys() & counts_new.keys(),
        key=lambda line: counts_old[line] * counts_new[line],
    )
    followed = 0
    chosen = set()
    for line in shared:
        pairs = counts_old[line] * counts_new[line]
        if followed + pairs > most:
            break
        followed += pairs
        chosen.add(line)
    where = {}
    for j in range(len(new) - 1, -1, -1):
        line = new[j]
        if line in chosen:
            where.setdefault(line, []).append(j)
    tails = []
    for places in filter(None, map(where.get, old)):
        for j in places:
            k = bisect_left(tails, j)
            if k == len(tails):
                tails.append(j)
            else:
                tails[k] = j
    return len(tails), followed
