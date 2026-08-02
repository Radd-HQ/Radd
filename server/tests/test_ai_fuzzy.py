"""The NL→SLQ fuzzy value matcher (pure): first names find full names,
diacritics fold, prefixes work, and garbage stays unmatched (below the
threshold the ordinary compile error must surface, never a wrong person)."""

from radd.modules.ai.fuzzy import MATCH_THRESHOLD, best_match, score

PEOPLE = [
    "Jimmy Lee Barlow",
    "James Holden",
    "Hussein Jarrar",
    "René Lévesque",
    "Kim Yee",
]


def test_first_name_finds_the_full_name():
    match = best_match("jimmy", PEOPLE)
    assert match is not None and match.value == "Jimmy Lee Barlow"
    assert match.confidence >= 0.9


def test_last_name_and_prefix_work():
    assert best_match("barlow", PEOPLE).value == "Jimmy Lee Barlow"
    assert best_match("jim", PEOPLE).value == "Jimmy Lee Barlow"  # prefix of a word
    assert best_match("holden", PEOPLE).value == "James Holden"


def test_diacritics_fold_both_ways():
    assert best_match("rene", PEOPLE).value == "René Lévesque"
    assert best_match("RENÉ", PEOPLE).value == "René Lévesque"
    assert best_match("levesque", PEOPLE).value == "René Lévesque"


def test_multiword_query_covers_tokens():
    assert best_match("jimmy barlow", PEOPLE).value == "Jimmy Lee Barlow"


def test_exact_beats_fuzzy_and_scores_one():
    assert score("Hussein Jarrar", "Hussein Jarrar") == 1.0
    assert best_match("hussein jarrar", PEOPLE).value == "Hussein Jarrar"


def test_garbage_stays_unmatched():
    assert best_match("zzzzqqqq", PEOPLE) is None
    assert best_match("", PEOPLE) is None
    # A two-letter fragment is a guess, not a match.
    assert best_match("jz", PEOPLE) is None


def test_close_call_still_prefers_the_right_token():
    # "kim" must hit Kim Yee, not the 'im' inside Jimmy.
    assert best_match("kim", PEOPLE).value == "Kim Yee"


def test_first_name_beats_a_surname_tie():
    # Both carry the exact token; the person CALLED Laurent wins the tie.
    people = ["Julie Ashworth", "Laurent Okafor-Reyes"]
    assert best_match("laurent", people).value == "Laurent Okafor-Reyes"
    # Asking by the surname still finds the surname holder.
    assert best_match("ashworth", people).value == "Julie Ashworth"


def test_threshold_is_honest():
    accepted = best_match("jimy", PEOPLE)  # typo'd first name still lands
    assert accepted is not None and accepted.value == "Jimmy Lee Barlow"
    assert accepted.confidence >= MATCH_THRESHOLD


def test_non_people_values_work_the_same():
    states = ["In Progress", "Needs Discussion", "Done", "Canceled"]
    assert best_match("in progress", states).value == "In Progress"
    assert best_match("discussing", states).value == "Needs Discussion"
    assert best_match("progress", states).value == "In Progress"
