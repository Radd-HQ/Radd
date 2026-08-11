#!/bin/sh
# One-time setup for a dev Garage container (spec 102) — run AFTER
#   podman compose -f compose.dev.yaml --profile storage up -d garage-1 garage-2
# then once per instance:
#   sh deploy/garage/init.sh garage-1
#   sh deploy/garage/init.sh garage-2
#
# Lays out the single node, creates the dev bucket, and imports FIXED dev-only
# credentials so Settings → Storage can be filled straight from here:
#
#   host_type   s3
#   endpoint    localhost:3900   (garage-1)   /   localhost:3910   (garage-2)
#   bucket      radd-dev
#   access key  GK647261646464657630313233
#   secret key  6472616464646576736563726574303030303030303030303030303030303030
#   region      garage           (Garage signs against its s3_region!)
#   secure      off (plain http)
set -e
SERVICE="${1:-garage-1}"

# Which stack's Garage to set up. Defaults to the working one, so the documented
# one-liner above is unchanged; `scripts/dev-clean.sh` points it at the clean
# stack, whose containers live in another compose project entirely.
COMPOSE_FILE="${RADD_COMPOSE_FILE:-compose.dev.yaml}"
COMPOSE_PROFILE="${RADD_COMPOSE_PROFILE:---profile storage}"

# shellcheck disable=SC2086 - COMPOSE_PROFILE is deliberately word-split (it may be empty).
g() { podman compose -f "$COMPOSE_FILE" $COMPOSE_PROFILE exec -T "$SERVICE" /garage "$@"; }

ACCESS="GK647261646464657630313233"
SECRET="6472616464646576736563726574303030303030303030303030303030303030"

NODE_ID=$(g status | awk '/HEALTHY NODES/{found=1; next} found && !/Hostname/ && NF {print $1; exit}')
echo "node: $NODE_ID"
g layout assign -z dev -c 10G "$NODE_ID" || true
g layout apply --version 1 || true
g bucket create radd-dev || true
g key import "$ACCESS" "$SECRET" -n radd-dev-key --yes || true
g bucket allow radd-dev --read --write --key radd-dev-key || true
g bucket info radd-dev
