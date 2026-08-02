# CloudNativePG's Postgres image plus pgvector, for Radd's semantic search.
#
# The stock CNPG images don't ship pgvector, and Radd's embeddings schema is
# created at runtime behind a guarded `CREATE EXTENSION vector` — so without
# this the instance simply falls back to plain FTS (nothing breaks, spec 103).
#
#   podman build -f pgvector.Containerfile -t cnpg-pgvector:16 .
#
# CNPG images are Debian-based with the PGDG apt repository already configured,
# which is where postgresql-16-pgvector comes from. Pin the base tag to the
# same major CNPG is running; bump both together.
FROM ghcr.io/cloudnative-pg/postgresql:16.4-bookworm

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*

# CNPG requires the image to run as the postgres uid it manages.
USER 26
