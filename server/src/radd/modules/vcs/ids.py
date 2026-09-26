"""The ONE spelling of a connector's external ids (RADD-1124): webhook, backfill and
CI stamp must produce the same id or the panel grows twins and CI lands on neither.
The repository segment is lowercased (hosts treat `Radd-HQ/Radd` = `radd-hq/radd`).
"""


def _repo(repo_name: str) -> str:
    return repo_name.strip().lower()


def commit_external_id(repo_name: str, sha: str) -> str:
    return f"commit:{_repo(repo_name)}:{sha}"


def branch_external_id(repo_name: str, branch: str) -> str:
    return f"branch:{_repo(repo_name)}:{branch}"


def pr_external_id(repo_name: str, number: int | str) -> str:
    return f"pr:{_repo(repo_name)}:{number}"
