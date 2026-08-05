#!/usr/bin/env python3
"""Bulk-provision users from Active Directory (spec 49).

Binds with the SERVICE ACCOUNT (RADD_LDAP_BIND_DN / RADD_LDAP_BIND_PASSWORD) to
enumerate the directory, then creates each user in Radd via the REST API. Created
accounts are matched to their AD identity BY EMAIL, so a later interactive
sign-in (direct bind, spec 42) links up and syncs the real role. This is the one
place a bind account is used — interactive login never stores one.

    RADD_LDAP_URL=ldaps://ad.example.com:636 RADD_LDAP_USER_DOMAIN=ad.example.com \
    RADD_LDAP_BIND_DN='CN=svc-radd,OU=...,DC=ad,DC=example,DC=com' \
    RADD_LDAP_BIND_PASSWORD=... \
    uv run python scripts/import_ad_users.py --email admin@example.com --password ... [--dry-run]

The service password is read from the environment only — never a CLI flag.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys

import httpx

# radd.config reads RADD_LDAP_* from the environment; the ldap service does the bind.
from radd.modules.ldap import service as ldap_service

DEFAULT_API = "http://localhost:8000/api/v1"


async def _resolved_user_base() -> str:
    """The cascade-resolved search base (Settings → Directory beats env) — the
    script opens a short-lived DB session for it, so it can never disagree with
    what the settings page shows (RADD-895 removed the raw-env fallback)."""
    from radd.db import SessionLocal

    async with SessionLocal() as session:
        return await ldap_service.resolved_user_base(session)


def provision(api: httpx.Client, users: list, dry_run: bool) -> tuple[int, int, int]:
    created = existing = errors = 0
    for user in users:
        if dry_run:
            print(f"  would create: {user.email}  ({user.name})")
            created += 1
            continue
        payload = {
            "email": user.email,
            "name": user.name,
            # Random secret: these accounts authenticate via AD (direct bind by email).
            "password": secrets.token_urlsafe(24),
            "instance_role": "member",
        }
        resp = api.post("/users", json=payload)
        if resp.status_code in (200, 201):
            created += 1
        elif resp.status_code == 409:
            existing += 1
        else:
            errors += 1
            print(f"  ERROR {user.email}: {resp.status_code} {resp.text}", file=sys.stderr)
    return created, existing, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=os.environ.get("RADD_API", DEFAULT_API))
    parser.add_argument("--token", default=os.environ.get("RADD_TOKEN"))
    parser.add_argument("--email", default=os.environ.get("RADD_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("RADD_PASSWORD"))
    parser.add_argument("--dry-run", action="store_true", help="enumerate only; create nothing")
    args = parser.parse_args()

    if not ldap_service.bind_account_enabled():
        print("fatal: set RADD_LDAP_URL, RADD_LDAP_BIND_DN and RADD_LDAP_BIND_PASSWORD",
              file=sys.stderr)
        return 1

    base = asyncio.run(_resolved_user_base())
    print(f"binding {os.environ.get('RADD_LDAP_BIND_DN')} and enumerating {base} ...")
    directory_users = ldap_service.search_directory_users("", base)
    print(f"found {len(directory_users)} directory users with an email")

    api = None
    if not args.dry_run:  # a dry run enumerates only — no Radd API needed
        headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
        api = httpx.Client(base_url=args.api, headers=headers, timeout=30.0)
        if not args.token:
            if not (args.email and args.password):
                print("fatal: provide --token or --email/--password for the Radd API",
                      file=sys.stderr)
                return 1
            if api.post(
                "/auth/login", json={"email": args.email, "password": args.password}
            ).status_code != 204:
                print("fatal: Radd login failed", file=sys.stderr)
                return 1

    created, existing, errors = provision(api, directory_users, args.dry_run)
    print(f"\ncreated={created} existing={existing} errors={errors}"
          + ("  (dry run)" if args.dry_run else ""))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
