#!/bin/sh
# Shims for pg_dump / pg_restore / psql of ONE PostgreSQL major, run from the
# official image (RADD-1543). The restore drill must use the client major the
# shipped image carries, not whichever happens to be installed: client 17 could
# not restore into a 16 server, and tools that matched the server hid it.
#
#   sh scripts/pg_client_shims.sh 17 /tmp/pg17   # then point RADD_BACKUP_*_PATH at /tmp/pg17/*
#
# Paths under /tmp are shared with the container; the drills keep their files there.
set -eu
major="$1"; target="$2"; runtime="${RADD_CONTAINER_RUNTIME:-docker}"
mkdir -p "$target"
for tool in pg_dump pg_restore psql; do
  printf '#!/bin/sh\nexec %s run --rm -i --network host -v /tmp:/tmp -e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD -e PGDATABASE docker.io/library/postgres:%s %s "$@"\n' \
    "$runtime" "$major" "$tool" > "$target/$tool"
  chmod +x "$target/$tool"
done
"$target/pg_restore" --version
