"""The ONE spelling of a connector's external ids (RADD-1124).

`item_vcs_links` is unique on (item, provider, external_id), and every path that
touches a ref — a webhook, a backfill walk, a CI stamp — has to produce the same
string for the same ref or the panel grows twins and CI lands on none of them.
The Forgejo webhook once wrote a commit as its bare SHA while the backfill wrote
`commit:<repo>:<sha>`, so a backfill after a webhook duplicated every commit and
a workflow run never found the webhook's row. GitHub and Forgejo now share these
three functions; a connector that needs a fourth shape adds it HERE.

The repository segment is LOWERCASED: a host reports `Radd-HQ/Radd` in a payload
while an admin types `radd-hq/radd` into the repository row, and both hosts treat
the two as the same repository.
"""


def _repo(repo_name: str) -> str:
    return repo_name.strip().lower()


def commit_external_id(repo_name: str, sha: str) -> str:
    return f"commit:{_repo(repo_name)}:{sha}"


def branch_external_id(repo_name: str, branch: str) -> str:
    return f"branch:{_repo(repo_name)}:{branch}"


def pr_external_id(repo_name: str, number: int | str) -> str:
    return f"pr:{_repo(repo_name)}:{number}"
