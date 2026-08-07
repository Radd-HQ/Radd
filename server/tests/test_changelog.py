"""The release-notes generator's pure half (RADD-942).

`scripts/changelog.py` is invoked by CI at tag time, so nothing about it runs in
the app and nothing about it is type-checked against the renderers it feeds. The
0.25.0 notes shipped with `## What is wrong` as the summary of all twelve
entries and `<sub>` printed literally beside every one of them — both defects
are in two pure functions, and both are one assertion each.

What is pinned here is what a RENDERER will do with the output, not just what the
string looks like: no raw HTML (Radd's CommonMark viewer escapes it), and no
line that can start a block (an ATX heading interrupts a paragraph, which is how
a summary escaped the bullet it belonged to).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from changelog import Changelog, Entry, _entry_lines, _lead, render_markdown  # noqa: E402

BASE = "https://project.radd-hq.com"
REPO = "https://git.radd-hq.com/Radd/Radd"


# --- the summary ---------------------------------------------------------------


@pytest.mark.parametrize(
    "description, expected",
    [
        # The shape EVERY body in this tracker actually has.
        ("## What is wrong\n\nThe grid says 4.", "The grid says 4."),
        ("### What is wanted\n\nA queue view.", "A queue view."),
        # The inline label the older bodies use.
        ("**What is wrong.** The role was reset.", "The role was reset."),
        ("**What is wanted:** a queue view.", "a queue view."),
        # A heading that is a label AND carries the claim.
        ("## What changes: the catalog carries qualifiers", "the catalog carries qualifiers"),
        # The contraction several bodies actually use — and with the typographic
        # apostrophe the editor produces, which is a different string entirely.
        ("**What's wrong.** The tree orders siblings wrongly.", "The tree orders siblings wrongly."),
        ("**What’s wrong.** The tree orders siblings wrongly.", "The tree orders siblings wrongly."),
        ("## What's missing\n\nA queue view.", "A queue view."),
        # No label at all — the first paragraph is the claim.
        ("The board clips at five cards.\n\n## Where\n\n`board.tsx`", "The board clips at five cards."),
    ],
)
def test_the_summary_is_the_claim_not_the_heading_above_it(description, expected):
    assert _lead(description) == expected


def test_a_fenced_block_is_never_the_summary():
    """Blocks are split on blank lines, and a fence can contain them — a code
    sample would otherwise become a one-line summary of shell output."""
    body = "## What is wrong\n\n```\nitem.read@own\n\nitem.read@team\n```\n\nThe matrix cannot draw them."
    assert _lead(body) == "The matrix cannot draw them."


def test_the_summary_can_never_start_a_block():
    """The summary is inlined into a list item. Anything that opens a block
    breaks OUT of it — the 0.25.0 failure, where `##` rendered as a heading."""
    for opener in ("## ", "> ", "- ", "1. "):
        assert not _lead(f"{opener}Something happened.").startswith(opener.strip())


def test_a_long_lead_is_truncated_on_a_word_boundary():
    summary = _lead("## What is wrong\n\n" + "word " * 200)
    assert summary.endswith("…") and len(summary) <= 321


# --- the rendered entry ---------------------------------------------------------


def _entry() -> Entry:
    return Entry(
        key="RADD-939",
        subject="[RADD-939] the roles matrix",
        sha="b74ca6d1",
        title="The roles matrix cannot show or edit relation-qualified atoms",
        category="Bugfix",
        labels=("web",),
        points=3,
        summary="Baseline reports 11 permissions beside a grid that can express 4.",
    )


def test_an_entry_emits_no_html():
    """Two destinations, one body: Forgejo renders inline HTML, Radd's viewer
    escapes it. The intersection is the budget."""
    assert "<" not in "\n".join(_entry_lines(_entry(), BASE, REPO))


def test_continuation_lines_carry_a_hard_break():
    """Consecutive lines in a list item are lazy continuation — without the two
    trailing spaces the title, the claim and the sha render as one paragraph."""
    lines = _entry_lines(_entry(), BASE, REPO)
    assert [line.endswith("  ") for line in lines] == [True, True, False]


def test_the_claim_comes_before_the_provenance():
    lines = _entry_lines(_entry(), BASE, REPO)
    assert "grid that can express 4" in lines[1]
    assert "b74ca6d1" in lines[2] and "`web`" in lines[2]


def test_a_degraded_entry_still_renders():
    """The tracker being unreachable means no title, no labels, no summary —
    a release must still publish."""
    lines = _entry_lines(Entry(key=None, subject="[RADD-1] fixed the thing", sha="abc123"), BASE, "")
    assert lines == ["- **fixed the thing**  ", "  `abc123`"]


def test_the_whole_body_is_html_free():
    log = Changelog(version="v0.25.0", previous="v0.24.1", entries=[_entry()])
    body = render_markdown(log, BASE, REPO)
    assert "<" not in body
    assert "**1 change**" in body and "1 Bugfix" in body
