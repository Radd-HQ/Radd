"""Attach files to a version's release on the git host (RADD-1026).

    release_assets.py --tag v0.32.0 file [file ...]

The release is found or created (the changelog step usually made it first);
a same-named asset is replaced, so re-running a version updates its documents
instead of growing duplicates. Host and token selection: release_host.py
(GitHub inside GitHub Actions, Forgejo otherwise).
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_host  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()

    host = release_host.from_env()
    if not host.token:
        print(f"! no {host.kind} token — cannot attach release assets", file=sys.stderr)
        return 1
    missing = [f for f in args.files if not os.path.isfile(f)]
    if missing:
        print(f"! not a file: {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        release = host.find_or_create_release(args.tag, f"Radd {args.tag.lstrip('v')}")
        for path in args.files:
            print(f"asset: {host.attach(release, path)}")
    except (urllib.error.URLError, OSError, KeyError) as exc:
        print(f"! attaching assets to {args.tag} failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
