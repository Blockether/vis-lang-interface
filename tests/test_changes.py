"""`line_changes` counts the changed lines `git diff --minimal --numstat` counts."""

import random
import re
import shutil
import subprocess

import pytest

from vis_lang_interface import changes, line_changes

_REPEATING = ("a", "b", "c", "", "  (x)", "a\r", "}")

_CASES = [
    ("", "", (0, 0)),
    ("a\nb\n", "a\nb\n", (0, 0)),
    ("", "a\nb\n", (2, 0)),
    ("a\nb\n", "", (0, 2)),
    ("a\nb\nc\n", "a\nB\nc\nd\n", (2, 1)),
    ("a\nb\n", "b\na\n", (1, 1)),
    ("a", "a\n", (1, 1)),
    ("a\n", "a", (1, 1)),
    ("a\r\nb\r\n", "a\nb\n", (2, 2)),
    ("a\n\n\nb\n", "a\n\nb\n", (0, 1)),
]


def _longest(old, new):
    """Length of a longest common subsequence, from the textbook table."""
    row = [0] * (len(new) + 1)
    for line in old:
        diagonal = 0
        for j, other in enumerate(new, 1):
            above = row[j]
            row[j] = diagonal + 1 if line == other else max(above, row[j - 1])
            diagonal = above
    return row[-1]


def _fewest(before, after):
    """`(added, removed)` of a minimal line diff, each line with its newline."""
    old = re.findall(r"[^\n]*\n|[^\n]+\Z", before)
    new = re.findall(r"[^\n]*\n|[^\n]+\Z", after)
    kept = _longest(old, new)
    return len(new) - kept, len(old) - kept


def _pairs(old, new):
    """Pairs of equal lines between two line lists."""
    return sum(new.count(line) for line in old)


def _text(rng, lines):
    """The lines joined, most of the time ending with a newline."""
    return "\n".join(lines) + ("\n" if lines and rng.random() < 0.8 else "")


def _pair(rng, most=30):
    """Two texts of a few repeating lines: one an edit of the other, or unrelated."""
    lines = _REPEATING[: rng.randint(2, len(_REPEATING))]
    before = [rng.choice(lines) for _ in range(rng.randint(0, most))]
    if rng.random() < 0.3:
        after = [rng.choice(lines) for _ in range(rng.randint(0, most))]
        return _text(rng, before), _text(rng, after)
    after = list(before)
    for _ in range(rng.randint(0, 6)):
        at = rng.randint(0, len(after))
        roll = rng.random()
        if roll < 0.4 or not after:
            after.insert(at, rng.choice(lines))
        elif roll < 0.8:
            del after[at - 1]
        else:
            start = rng.randrange(len(after))
            block = after[start : start + rng.randint(1, 5)]
            del after[start : start + len(block)]
            after[at:at] = block
    return _text(rng, before), _text(rng, after)


def _git_numstat(directory, before, after):
    """`(added, removed)` that `git diff --minimal --numstat` reports for two texts."""
    (directory / "before").write_bytes(before.encode())
    (directory / "after").write_bytes(after.encode())
    done = subprocess.run(
        [
            *("git", "-c", "core.autocrlf=false", "diff", "--no-index"),
            *("--no-ext-diff", "--no-textconv", "--diff-algorithm=myers"),
            *("--minimal", "--numstat", "before", "after"),
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode in (0, 1), done.stderr
    fields = done.stdout.split()
    return (int(fields[0]), int(fields[1])) if fields else (0, 0)


@pytest.mark.parametrize(("before", "after", "counts"), _CASES)
def test_a_line_counts_with_its_newline(before, after, counts):
    assert line_changes(before, after) == counts


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_counts_agree_with_git_minimal_numstat(tmp_path):
    rng = random.Random(1)
    pairs = [(before, after) for before, after, _ in _CASES]
    pairs += [_pair(rng, most=60) for _ in range(40)]
    for before, after in pairs:
        assert line_changes(before, after) == _git_numstat(tmp_path, before, after)


def test_counts_the_fewest_changed_lines():
    rng = random.Random(2)
    for _ in range(3000):
        before, after = _pair(rng)
        assert line_changes(before, after) == _fewest(before, after), (before, after)


@pytest.mark.parametrize("edits", [1, 10, 60, 400])
def test_long_texts_count_exactly(edits):
    rng = random.Random(edits)
    before = [f"line {rng.randrange(300)}" for _ in range(500)]
    after = list(before)
    for _ in range(edits):
        at = rng.randrange(len(after))
        if rng.random() < 0.5:
            after[at] = f"line {rng.randrange(300)}"
        else:
            after.insert(at, after.pop(rng.randrange(len(after))))
    before, after = "\n".join(before) + "\n", "\n".join(after) + "\n"
    assert line_changes(before, after) == _fewest(before, after)


def test_each_exact_count_finds_a_longest_common_subsequence():
    rng = random.Random(3)
    for _ in range(1000):
        old, new = map(changes._lines, _pair(rng))
        longest = _longest(old, new)
        assert changes._myers(old, new, 10**9) == longest
        assert changes._bit_parallel(old, new) == longest
        assert changes._sparse(old, new, 10**9) == (longest, _pairs(old, new))


def test_bit_parallel_rows_give_up_past_the_mask_limit(monkeypatch):
    monkeypatch.setattr(changes, "_MOST_MASK_BITS", 2)
    assert changes._bit_parallel(["a", "b"], ["b", "a", "b"]) is None
    assert changes._bit_parallel(["a", "b"], ["b", "a", "c"]) == 1


@pytest.mark.parametrize(
    "budgets",
    [
        {"_MOST_STEPS": 30},
        {"_MOST_STEPS": 0},
        {"_MOST_STEPS": 0, "_MOST_PAIRS": 5},
        {"_MOST_MASK_BITS": 0},
    ],
)
def test_counts_past_a_budget_are_never_below_the_fewest(monkeypatch, budgets):
    for name, value in budgets.items():
        monkeypatch.setattr(changes, name, value)
    rng = random.Random(4)
    for _ in range(2000):
        before, after = _pair(rng)
        added, removed = line_changes(before, after)
        fewest_added, fewest_removed = _fewest(before, after)
        assert added >= fewest_added and removed >= fewest_removed, (before, after)
