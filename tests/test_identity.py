"""Tests for GitHub <-> git identity matching and row consolidation (STAT-11).

All names, emails and logins here are invented.
"""

import copy

from gitlogstats.git_logs_parser import FIELDNAMES
from gitlogstats.github import GITHUB_FIELDNAMES
from gitlogstats.identity import (
    consolidate,
    login_from_noreply,
    match_identities,
    normalize_display_name,
    normalize_login,
    unavailable_row,
)


def cand(name=None, email=None):
    return {"name": name, "email": email}


def git_row(username, commits=1, **extra):
    row = {
        "username": username,
        "repository": "repo",
        "start_date": "01/01/2024",
        "end_date": "12/31/2024",
        "commits": commits,
        "insertions": 10,
        "deletions": 2,
        "files": 3,
        "merges": 0,
    }
    row.update(extra)
    return row


# ---- helpers ----------------------------------------------------------------


def test_login_from_noreply_forms():
    assert login_from_noreply("123+ada-l@users.noreply.github.com") == "ada-l"
    assert login_from_noreply("ada-l@users.noreply.github.com") == "ada-l"
    assert login_from_noreply("123+Ada@Users.NoReply.GitHub.com") == "Ada"
    assert login_from_noreply("ada@example.com") is None
    assert login_from_noreply("ada@evil.users.noreply.github.com.x.org") is None
    assert login_from_noreply("") is None
    assert login_from_noreply(None) is None


def test_normalize_login():
    assert normalize_login("Ada Love_lace-X.y") == "adalovelacexy"
    assert normalize_login(None) == ""


def test_normalize_display_name():
    assert normalize_display_name("Ada Lovelace") == ("ada", "lovelace")
    assert normalize_display_name("Lovelace, Ada") == ("ada", "lovelace")
    assert normalize_display_name("  ada   LOVELACE ") == ("ada", "lovelace")
    assert normalize_display_name("José Núñez") == normalize_display_name("Jose Nunez")
    assert normalize_display_name("") == ()
    assert normalize_display_name(None) == ()
    assert normalize_display_name(" - , ") == ()


# ---- tier 1: email ----------------------------------------------------------


def test_noreply_email_matches_even_when_not_a_candidate():
    ids = {
        "Ada Lovelace": {
            "ada-l@users.noreply.github.com",
            "7+ada-l@Users.noreply.github.com",
        }
    }
    matches, amb = match_identities(ids, {}, {})
    assert matches == {"Ada Lovelace": ("ada-l", "email")}
    assert amb == {}


def test_noreply_spelling_follows_candidates():
    ids = {"x": {"7+ADA-L@users.noreply.github.com"}}
    matches, _ = match_identities(ids, {"Ada-L": cand()}, {})
    assert matches["x"] == ("Ada-L", "email")


def test_linked_email_matches_case_insensitively():
    ids = {"ange": {"Ange@Example.com"}}
    matches, _ = match_identities(ids, {}, {"ange@example.com": "AngeLogin"})
    assert matches == {"ange": ("AngeLogin", "email")}


def test_linked_email_none_is_ignored():
    ids = {"zed": {"z@example.com"}}
    matches, amb = match_identities(ids, {}, {"z@example.com": None})
    assert matches == {} and amb == {}


def test_public_profile_email_matches_case_insensitively():
    ids = {"local-name": {"Bob@Example.com"}, "bob_local": {"bob@example.com"}}
    cands = {"bobhub": cand(email="BOB@example.com")}
    matches, _ = match_identities(ids, cands, {})
    assert matches == {
        "local-name": ("bobhub", "email"),
        "bob_local": ("bobhub", "email"),
    }


def test_same_login_from_several_sources_is_not_ambiguous():
    ids = {"a": {"1+Bobhub@users.noreply.github.com", "b@example.com"}}
    cands = {"bobhub": cand(email="b@example.com")}
    matches, amb = match_identities(ids, cands, {"b@example.com": "BOBHUB"})
    assert matches == {"a": ("bobhub", "email")}
    assert amb == {}


def test_email_tier_ambiguous_falls_through_to_username():
    ids = {"carol": {"c1@example.com", "c2@example.com"}}
    cands = {"carol": cand(), "other": cand(), "third": cand()}
    linked = {"c1@example.com": "other", "c2@example.com": "third"}
    matches, amb = match_identities(ids, cands, linked)
    assert matches == {"carol": ("carol", "username")}
    assert amb == {"carol": ["email"]}


def test_ambiguity_recorded_and_unmatched_when_all_tiers_fail():
    ids = {"carol": {"c1@example.com", "c2@example.com"}}
    linked = {"c1@example.com": "one", "c2@example.com": "two"}
    matches, amb = match_identities(ids, {"one": cand(), "two": cand()}, linked)
    assert matches == {}
    assert amb == {"carol": ["email"]}


def test_email_tier_wins_over_username_tier():
    ids = {"dave": {"d@example.com"}}
    cands = {"dave": cand(), "dave-real": cand()}
    matches, _ = match_identities(ids, cands, {"d@example.com": "dave-real"})
    assert matches == {"dave": ("dave-real", "email")}


# ---- tier 2: username -------------------------------------------------------


def test_username_ignores_case_spaces_and_separators():
    ids = {"Jane Doe": {"jd@example.com"}}
    matches, _ = match_identities(ids, {"Jane-Doe": cand()}, {})
    assert matches == {"Jane Doe": ("Jane-Doe", "username")}


def test_username_matches_email_local_part():
    ids = {"J. Smith": {"jsmith_99@example.com"}}
    matches, _ = match_identities(ids, {"JSmith-99": cand()}, {})
    assert matches == {"J. Smith": ("JSmith-99", "username")}


def test_username_equals_login_with_empty_display_name():
    ids = {"zoe285": {"zz@school.edu"}}
    matches, _ = match_identities(ids, {"zoe285": cand(name="")}, {})
    assert matches == {"zoe285": ("zoe285", "username")}


def test_generic_local_part_never_matches_a_login():
    ids = {"GitHub": {"noreply@github.com"}, "Pat Kim": {"admin@corp.example"}}
    cands = {"noreply": cand(), "admin": cand()}
    matches, _ = match_identities(ids, cands, {})
    assert matches == {}


def test_local_part_shared_by_two_authors_matches_neither():
    ids = {
        "Alex Smith": {"alex@gmail.example"},
        "Alex Jones": {"alex@school.example"},
    }
    matches, _ = match_identities(ids, {"alex": cand()}, {})
    assert matches == {}


def test_local_part_shared_by_one_author_still_matches():
    ids = {"A. Smith": {"alex@gmail.example", "alex@school.example"}}
    matches, _ = match_identities(ids, {"alex": cand()}, {})
    assert matches == {"A. Smith": ("alex", "username")}


def test_username_tier_ambiguous_leaves_author_unmatched():
    ids = {"sam.l": {"x@example.com"}}
    cands = {
        "saml": cand(name="Sam Lee"),
        "sam-l": cand(name="Other"),
    }
    matches, amb = match_identities(ids, cands, {})
    assert matches == {}
    assert amb == {"sam.l": ["username"]}


def test_empty_normalized_values_are_skipped():
    ids = {"...": {"@example.com", None}}
    cands = {"---": cand(name="")}
    matches, amb = match_identities(ids, cands, {})
    assert matches == {} and amb == {}


# ---- tier 3: display name ---------------------------------------------------


def test_display_name_word_order():
    ids = {"Seth Doe": {"s@local.edu"}}
    matches, _ = match_identities(ids, {"sdoe42": cand(name="Doe, Seth")}, {})
    assert matches == {"Seth Doe": ("sdoe42", "display_name")}


def test_display_name_accents():
    ids = {"Jose Nunez": {"j@local.edu"}}
    matches, _ = match_identities(ids, {"jn": cand(name="José Núñez")}, {})
    assert matches == {"Jose Nunez": ("jn", "display_name")}


def test_display_name_ambiguous_is_unmatched():
    ids = {"Pat Kim": {"p@local.edu"}}
    cands = {"pk1": cand(name="Pat Kim"), "pk2": cand(name="kim pat")}
    matches, amb = match_identities(ids, cands, {})
    assert matches == {}
    assert amb == {"Pat Kim": ["display_name"]}


def test_empty_display_name_never_matches_empty_author_name():
    ids = {"": {"e@local.edu"}, "--": {"f@local.edu"}}
    cands = {"a": cand(name=""), "b": cand(name=None), "c": cand(name="---")}
    matches, amb = match_identities(ids, cands, {})
    assert matches == {} and amb == {}


def test_missing_candidate_info_is_tolerated():
    matches, _ = match_identities({"a": {"a@x.org"}}, {"zz": None}, {})
    assert matches == {}


# ---- the real-data shapes ---------------------------------------------------


def test_one_person_two_author_names_merge_into_one_login():
    ids = {
        "sdoe": {"sd1@school.edu"},
        "Seth Doe": {"99+sdoe@users.noreply.github.com"},
    }
    cands = {"sdoe": cand(name="Seth Doe")}
    matches, _ = match_identities(ids, cands, {})
    assert matches == {
        "sdoe": ("sdoe", "username"),
        "Seth Doe": ("sdoe", "email"),
    }


def test_two_local_usernames_one_email_linked_to_account():
    ids = {
        "amy": {"amy@school.edu"},
        "amy_laptop": {"amy@school.edu"},
    }
    matches, _ = match_identities(ids, {"amyhub": cand()}, {"amy@school.edu": "amyhub"})
    assert matches == {
        "amy": ("amyhub", "email"),
        "amy_laptop": ("amyhub", "email"),
    }


def test_nickname_and_full_name_for_one_noreply_account():
    ids = {
        "Pip": {"pip@gmail.example"},
        "pip cruz": {"55+pip-cruz@users.noreply.github.com"},
    }
    matches, _ = match_identities(
        ids, {"pip-cruz": cand()}, {"pip@gmail.example": "pip-cruz"}
    )
    assert {v[0] for v in matches.values()} == {"pip-cruz"}
    assert len(matches) == 2


# ---- consolidate ------------------------------------------------------------


def pr(opened=0, merged=0, closed=0, self_merged=0):
    return {
        "prs_opened": opened,
        "prs_merged": merged,
        "prs_closed_unmerged": closed,
        "prs_self_merged": self_merged,
    }


def test_consolidate_sums_and_picks_busiest_username():
    rows = [
        git_row("zed", commits=2, insertions=5, deletions=1, files=1, merges=0),
        git_row("Alone", commits=1),
        git_row("Zed Full", commits=7, insertions=100, deletions=20, files=9, merges=3),
    ]
    matches = {"zed": ("zhub", "email"), "Zed Full": ("ZHUB", "username")}
    out = consolidate(rows, matches, {"zhub": pr(4, 3, 1, 2)}, "repo", "s", "e")
    assert [r["username"] for r in out] == ["Zed Full", "Alone"]
    merged = out[0]
    assert merged["commits"] == 9
    assert merged["insertions"] == 105
    assert merged["deletions"] == 21
    assert merged["files"] == 10
    assert merged["merges"] == 3
    assert merged["github_username"] == "zhub"
    assert (merged["prs_opened"], merged["prs_merged"]) == (4, 3)
    assert merged["prs_closed_unmerged"] == 1
    assert merged["prs_self_merged"] == 2
    assert merged["repository"] == "repo"
    assert merged["start_date"] == "01/01/2024"
    assert out[1]["github_username"] == ""
    assert out[1]["prs_opened"] == 0


def test_consolidate_tie_broken_alphabetically():
    rows = [git_row("beta", commits=3), git_row("alpha", commits=3)]
    matches = {"beta": ("u", "email"), "alpha": ("u", "email")}
    out = consolidate(rows, matches, {}, "repo", "s", "e")
    assert len(out) == 1
    assert out[0]["username"] == "alpha"
    assert out[0]["commits"] == 6


def test_consolidate_position_of_first_member():
    rows = [git_row("a"), git_row("b"), git_row("c"), git_row("d")]
    matches = {"a": ("one", "email"), "c": ("one", "email")}
    out = consolidate(rows, matches, {}, "repo", "s", "e")
    assert [r["username"] for r in out] == ["a", "b", "d"]
    assert out[0]["commits"] == 2


def test_consolidate_column_order_and_zero_counts():
    rows = [git_row("a")]
    out = consolidate(rows, {"a": ("ahub", "email")}, {}, "repo", "s", "e")
    assert list(out[0]) == FIELDNAMES + GITHUB_FIELDNAMES
    assert out[0]["github_username"] == "ahub"
    assert out[0]["prs_opened"] == out[0]["prs_merged"] == 0
    assert out[0]["prs_self_merged"] == 0


def test_consolidate_github_only_rows_sorted_after_git_rows():
    rows = [git_row("a")]
    counts = {"Zed": pr(1), "ahub": pr(2, 1), "bob": pr(0, 1, 3, 1)}
    out = consolidate(rows, {"a": ("AHUB", "email")}, counts, "repo", "S", "E")
    assert [r["github_username"] for r in out] == ["AHUB", "bob", "Zed"]
    assert out[0]["prs_opened"] == 2
    only = out[1]
    assert only["username"] == ""
    assert only["prs_closed_unmerged"] == 3
    assert only["prs_self_merged"] == 1
    assert (only["repository"], only["start_date"], only["end_date"]) == (
        "repo",
        "S",
        "E",
    )
    for field in ["commits", "insertions", "deletions", "files", "merges"]:
        assert only[field] == 0
    for r in out:
        assert list(r) == FIELDNAMES + GITHUB_FIELDNAMES


def test_consolidate_does_not_mutate_inputs():
    rows = [git_row("a", commits=2), git_row("b", commits=1)]
    matches = {"a": ("u", "email"), "b": ("u", "email")}
    counts = {"u": pr(1), "v": pr(2)}
    before = copy.deepcopy((rows, matches, counts))
    consolidate(rows, matches, counts, "repo", "s", "e")
    assert (rows, matches, counts) == before


def test_unavailable_row():
    row = git_row("a")
    out = unavailable_row(row)
    assert list(out) == FIELDNAMES + GITHUB_FIELDNAMES
    assert all(out[f] is None for f in GITHUB_FIELDNAMES)
    assert out["commits"] == 1
    assert "github_username" not in row
