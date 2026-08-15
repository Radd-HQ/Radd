#!/usr/bin/env bash
# Pre-publication gate (RADD-1083): refuses a tree that still carries traces
# the public repository must not ship. Run from the repo root; exits non-zero
# on any hit, printing every offender.
#
# Two layers:
#   1. Generic classes checked right here — machine-absolute paths, private
#      IPs, key/dump files, tracked .env.
#   2. var/publish-denylist.txt — one case-insensitive pattern per line for
#      the specific names this operator must never publish (origin company,
#      internal hostnames, …). Kept UNTRACKED on purpose: a tracked denylist
#      would ship the very words it exists to block. The gate REFUSES to pass
#      when the file is missing, so forgetting it fails loud, not silent.
set -uo pipefail

fail=0
say() { printf '%s\n' "$*"; }

tracked() { git ls-files; }

check() { # check <label> <grep-args...>
  local label="$1"; shift
  local hits
  hits=$(tracked | xargs -d '\n' grep -lI "$@" 2>/dev/null)
  if [ -n "$hits" ]; then
    say "FAIL: $label"
    printf '%s\n' "$hits" | sed 's/^/    /'
    fail=1
  fi
}

# --- 1. generic classes ---------------------------------------------------
# (No generic RFC1918 check: the tree legitimately shows 10.x placeholders in
# deploy examples, CIDR test fixtures and UI hints. The denylist carries the
# operator's REAL ranges, which is the check that means something.)
check "machine-absolute paths" -e '/Volumes/''Work/' -e '<home>'

bad_files=$(tracked | grep -E '(^|/)\.env$|\.(pem|p12|pfx|key)$|reconcile_.*\.json$' || true)
if [ -n "$bad_files" ]; then
  say "FAIL: tracked secret/dump-shaped files"; printf '%s\n' "$bad_files" | sed 's/^/    /'; fail=1
fi

# --- 2. the operator's denylist --------------------------------------------
DENYLIST="var/publish-denylist.txt"
if [ ! -f "$DENYLIST" ]; then
  say "FAIL: $DENYLIST missing — the gate cannot vouch for a tree it hasn't screened."
  say "      One case-insensitive pattern per line (origin company, internal hosts…)."
  fail=1
else
  while IFS= read -r pat; do
    [ -z "$pat" ] && continue
    case "$pat" in \#*) continue ;; esac
    check "denylist: $pat" -i -e "$pat"
  done < "$DENYLIST"
fi

# --- 3. content-level secret scan, when the tool is around ------------------
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --no-git --source . --redact -v || fail=1
else
  say "note: gitleaks not installed — tree-level secret scan skipped (fine for"
  say "      a fresh-initial-commit publish; history never ships)."
fi

[ "$fail" -eq 0 ] && say "publish gate: CLEAN" || say "publish gate: REFUSED"
exit "$fail"
