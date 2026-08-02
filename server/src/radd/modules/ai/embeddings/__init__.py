"""Semantic-search embeddings (spec 103): pgvector schema + the embedder.

The tables live OUTSIDE Base.metadata on purpose — they exist only where the
`vector` extension does, are created/evolved by `ensure_schema()` at startup,
and their HNSW index is an expression-cast partial index the embedder manages
per active model. Alembic never sees them, so autogenerate stays quiet on
plain-Postgres deploys.
"""
