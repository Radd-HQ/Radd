"""Reconcile the whole Radd user list against Active Directory — the one-off
cleanup for an instance seeded by the Jira importer (spec 88).

The mess this fixes: the Jira import created accounts with placeholder addresses
(`alex.webb@example.com`) or with real addresses but `source=local`, so the same
human exists twice and the directory sync — which only ever renames ldap-source
accounts and matches on email — is inert for almost all of them.

Every account falls into exactly one bucket, decided by `ldap.userimport`'s
planner (the same matching the interactive import uses, so there is one
definition of "these are the same person"):

  ENFORCE  the exact AD email is already the account's address. Adopt AD's name
           and mark it `source=ldap` so the sync governs it from now on.
  MERGE    the account matches an AD person by display name only — a placeholder
           address. Fold it into the AD-identified account; everything it owns
           repoints, the duplicate is deactivated (kept for audit).
  KEEP     no AD counterpart. Leavers, sister-studio people and service accounts
           all live here, so this script NEVER touches them: it lists them and
           stops. Retiring them is a judgment call, not a reconcile.

Dry-run by default; nothing is written without --apply:

    uv run python scripts/reconcile_ad_users.py                 # report only
    uv run python scripts/reconcile_ad_users.py --apply         # enforce + merge
    uv run python scripts/reconcile_ad_users.py --apply --enforce-only

`--apply` writes a JSON audit file recording every account's before-state, so a
mistaken run can be reconstructed.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import select  # noqa: E402

from radd.db import SessionLocal  # noqa: E402
from radd.modules.auth import service as auth_service  # noqa: E402
from radd.modules.auth.models import User  # noqa: E402
from radd.modules.auth.types import UserSource  # noqa: E402
from radd.modules.ldap import service as ldap_service, userimport  # noqa: E402
from radd.modules.ldap.types import ImportResolution  # noqa: E402


async def _directory_users(session):
    base = await ldap_service.resolved_user_base(session)
    users = await asyncio.to_thread(ldap_service.search_directory_users, "", base)
    print(f"directory: {len(users)} users under {base}")
    return users


def _classify(directory_users, accounts):
    """Bucket every ACCOUNT (not every directory user) — the cleanup is about
    what is in Radd. Returns (enforce, merge, keep)."""
    by_email = {d.email.lower(): d for d in directory_users}
    by_name: dict[str, list] = {}
    for d in directory_users:
        by_name.setdefault(d.name.strip().lower(), []).append(d)

    enforce, merge, keep = [], [], []
    for account in accounts:
        exact = by_email.get(account.email.lower())
        if exact is not None:
            enforce.append((account, exact))
            continue
        namesakes = by_name.get(account.name.strip().lower(), [])
        # Only an UNAMBIGUOUS name match is actionable: if AD holds two people
        # with that display name there is no safe answer, so it stays in KEEP.
        if len(namesakes) == 1:
            merge.append((account, namesakes[0]))
        else:
            keep.append(account)
    return enforce, merge, keep


def _report(enforce, merge, keep, owners, by_radd_email):
    print(f"\n=== ENFORCE — {len(enforce)} accounts already at their AD address ===")
    renames = [(a, d) for a, d in enforce if d.name and a.name != d.name]
    claims = [(a, d) for a, d in enforce if a.source != UserSource.LDAP]
    print(f"  name refreshed : {len(renames)}")
    print(f"  claimed as ldap: {len(claims)}  (the sync will govern these afterwards)")
    for account, d in renames[:5]:
        print(f"    {account.email:38} {account.name!r} -> {d.name!r}")

    print(f"\n=== MERGE — {len(merge)} duplicate accounts under a placeholder address ===")
    for account, d in sorted(merge, key=lambda x: x[0].email):
        mark = "HAS WORK" if account.id in owners else "  empty "
        survivor = by_radd_email.get(d.email.lower())
        # Flagged, not blocked: the work still repoints to the right person, but
        # they end up with no ACTIVE account, which should not be a surprise.
        dead = "  [survivor is DEACTIVATED]" if survivor is not None and not survivor.active else ""
        print(f"  {mark}  {account.email:40} -> {d.email:34} ({account.name}){dead}")

    print(f"\n=== KEEP — {len(keep)} accounts with no AD counterpart (untouched) ===")
    with_work = sum(1 for a in keep if a.id in owners)
    print(f"  own work (historical authors — never delete): {with_work}")
    print(f"  empty: {len(keep) - with_work}  — service accounts and stale rows; review by hand")


async def _owner_ids(session) -> set:
    """Accounts that authored something — merging must preserve them, and the
    report flags them so an 'empty' row is never confused with a real one."""
    from sqlalchemy import text

    owners: set = set()
    for table, column in (
        ("work_items", "reporter_id"),
        ("work_items", "assignee_id"),
        ("comments", "author_id"),
        ("worklogs", "author_id"),
    ):
        rows = await session.execute(
            text(f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL")
        )
        owners |= {row[0] for row in rows}
    return owners


async def main(
    apply: bool,
    enforce_only: bool,
    merge_only: bool,
    exclude: set[str],
    exclude_prefixes: tuple[str, ...],
) -> None:
    def held_back(account) -> bool:
        email = account.email.lower()
        return email in exclude or email.startswith(exclude_prefixes)

    async with SessionLocal() as session:
        directory_users = await _directory_users(session)
        accounts = list((await session.execute(select(User))).scalars())
        print(f"radd: {len(accounts)} accounts")
        owners = await _owner_ids(session)
        enforce, merge, keep = _classify(directory_users, accounts)
        if exclude or exclude_prefixes:
            held = [a for a, _d in enforce + merge if held_back(a)]
            enforce = [(a, d) for a, d in enforce if not held_back(a)]
            merge = [(a, d) for a, d in merge if not held_back(a)]
            print(
                f"\nEXCLUDED {len(held)} account(s) — left exactly as they are"
                + (f" (prefixes: {', '.join(exclude_prefixes)})" if exclude_prefixes else "")
            )
            for account in sorted(held, key=lambda a: a.email):
                print(f"  held back: {account.email}")
        by_radd_email = {a.email.lower(): a for a in accounts}
        _report(enforce, merge, keep, owners, by_radd_email)

        if not apply:
            print("\nDRY RUN — nothing written. Re-run with --apply to execute.")
            return

        audit: dict[str, list] = {"enforced": [], "merged": []}
        if not merge_only:
            for account, directory_user in enforce:
                before = {"id": str(account.id), "email": account.email,
                          "name": account.name, "source": account.source}
                if await userimport.adopt_directory_identity(session, account, directory_user):
                    audit["enforced"].append(before)
        if not enforce_only:
            for account, directory_user in merge:
                before = {"id": str(account.id), "email": account.email,
                          "name": account.name, "source": account.source}
                survivor, _created = await userimport.apply_resolution(
                    session, directory_user, ImportResolution.MERGE, account.id
                )
                before["merged_into"] = str(survivor.id)
                audit["merged"].append(before)

        await session.commit()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(os.path.dirname(__file__), f"reconcile_ad_users_{stamp}.json")
        with open(path, "w") as handle:
            json.dump(audit, handle, indent=2)
        print(
            f"\nAPPLIED: {len(audit['enforced'])} enforced, {len(audit['merged'])} merged."
            f"\nAudit (before-state of every touched account): {path}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: report only)")
    parser.add_argument(
        "--enforce-only", action="store_true", help="skip the merges; only claim exact matches"
    )
    parser.add_argument(
        "--merge-only", action="store_true", help="skip the claims; only merge duplicates"
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="EMAIL",
        help="hold this account back from the run (repeatable) — e.g. an adm-* alias you keep",
    )
    parser.add_argument(
        "--exclude-prefix",
        action="append",
        default=[],
        metavar="PREFIX",
        help="hold back every account whose email starts with PREFIX (repeatable), e.g. adm-",
    )
    args = parser.parse_args()
    asyncio.run(
        main(
            args.apply,
            args.enforce_only,
            args.merge_only,
            {e.strip().lower() for e in args.exclude},
            tuple(p.strip().lower() for p in args.exclude_prefix),
        )
    )
