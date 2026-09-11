import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import Select, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.fields import service as fields_service
from radd.modules.projects import service as projects_service

from . import fusion
from .models import SearchIndexRow
from .types import (
    KEY_QUERY_RE,
    MAX_QUERY_CHARS,
    MIN_SEMANTIC_QUERY_CHARS,
    NUMBER_QUERY_RE,
    SEARCH_TS_CONFIG,
    SEMANTIC_CANDIDATES,
    TSQUERY_TOKEN_RE,
)

logger = logging.getLogger(__name__)


def build_tsquery(q: str) -> str:
    """User text → a safe prefix tsquery string: `render & farm:*`.

    Pure (tested): tokenizes on non-word separators (dropping tsquery
    metacharacters), ANDs the terms, and prefix-stars the LAST term so
    type-ahead matches mid-word. Empty result = nothing searchable.
    """
    tokens = TSQUERY_TOKEN_RE.findall(q[:MAX_QUERY_CHARS])
    if not tokens:
        return ""
    quoted = [f"'{token}'" for token in tokens]
    quoted[-1] += ":*"
    return " & ".join(quoted)


def looks_like_key(q: str) -> bool:
    return bool(KEY_QUERY_RE.match(q.strip()))


def key_pattern(q: str) -> str | None:
    """ILIKE pattern for key matching, or None when q isn't key-shaped.

    "TD-12" → prefix match; a bare number "123" → match the numeric part of any
    key (the `#123` habit — the editor's issue-mention popup sends exactly this).
    """
    if KEY_QUERY_RE.match(q):
        return f"{q}%"
    if NUMBER_QUERY_RE.match(q):
        return f"%-{q}%"
    return None


@dataclass(frozen=True)
class SearchHit:
    item_id: uuid.UUID
    project_id: uuid.UUID
    key: str
    title: str
    snippet: str | None


async def readable_project_ids(session: AsyncSession, user: User) -> set[uuid.UUID]:
    """Public seam (spec 103): the ai module scopes vector candidates with it."""
    return await _readable_project_ids(session, user)


async def _readable_project_ids(session: AsyncSession, user: User) -> set[uuid.UUID]:
    """Projects where the caller may read items — one batched authz pass.
    `holds_base` (RADD-823): a relation-qualified reader still counts; WHICH
    rows they see inside the project is `_relation_index_clause`'s job."""
    projects = await projects_service.list_projects(session)
    permissions = await authz.permissions_for_projects(session, user, projects)
    return {
        project.id
        for project in projects
        if authz.holds_base(permissions.get(project.id, frozenset()), Permission.ITEM_READ)
    }


def _scope(stmt: Select, readable: set[uuid.UUID], relation_clause=None) -> Select:
    stmt = stmt.where(SearchIndexRow.project_id.in_(readable))
    if relation_clause is not None:
        stmt = stmt.where(relation_clause)
    return stmt


# The relation keys the index MIRRORS as columns (RADD-841): a relation whose
# meaning is one of the item's OWN anchors is answered from search_index itself,
# because a mirror exists precisely so search never joins work_items. Every
# other registered item relation is compiled from its spec (RADD-1030) — see
# `_rebind_to_index`; the mirror set is the fast path, not the whole answer.
_INDEX_RELATION_COLUMNS = ("own", "assigned", "team")

# The table the registered item relations write their where-forms against, and
# whose primary key `search_index.item_id` mirrors.
_RELATION_SOURCE_TABLE = "work_items"

#: (relation key) already warned about — one line per key per process, not per
#: query. RADD-1040's rule, one module over.
_unmirrorable_warned: set[str] = set()


def _rebind_to_index(clause):
    """A registered item relation's where-form, re-anchored from `work_items.id`
    onto `search_index.item_id` — or None when that cannot be done (RADD-1030).

    Relations whose membership lives in ANOTHER table (`@participant`, RADD-844)
    are expressed as `WorkItem.id IN (SELECT … FROM item_participants …)`. Only
    the anchor names work_items; the predicate itself is about a different table
    entirely, so swapping the anchor for the mirror's `item_id` yields exactly
    the same set of item ids without search learning what the relation MEANS.
    That is why this compiles the REGISTERED spec rather than restating it: the
    owning plugin stays the single source of truth (participants' RelationSpec
    covers team-participant rows live, and a change there reaches search for
    free), and `search` names no plugin, so an unloaded one simply registers
    nothing.

    A rebound clause still touching `work_items` is REFUSED, not shipped: the
    d841 mirror rule ("search never joins work_items") is what keeps FTS one
    index scan, and a column relation like `@own` is already covered above.
    """
    from sqlalchemy.sql import visitors

    item_id = SearchIndexRow.item_id.__clause_element__()

    def _replace(element):
        table = getattr(element, "table", None)
        if (
            getattr(table, "name", None) == _RELATION_SOURCE_TABLE
            and getattr(element, "name", None) == "id"
        ):
            return item_id
        return None

    rebound = visitors.replacement_traverse(clause, {}, _replace)
    for element in visitors.iterate(rebound, {}):
        table = getattr(element, "table", None)
        if getattr(table, "name", None) == _RELATION_SOURCE_TABLE:
            return None
    return rebound


def _relation_clauses(relation_actor, held: set[str]) -> dict:
    """`relation key -> clause over search_index` for every relation the actor
    holds anywhere. The mirror columns are free; everything else registered on
    the item resource is compiled from ITS OWN spec (`_rebind_to_index`), so a
    plugin relation reaches search without search naming the plugin."""
    from sqlalchemy import false

    from radd.kernel import registries
    from radd.modules.auth.types import relation_contains

    clauses = {
        "own": SearchIndexRow.reporter_id == relation_actor.user_id,
        "assigned": SearchIndexRow.assignee_id == relation_actor.user_id,
        "team": (
            SearchIndexRow.team_id.in_(relation_actor.team_ids)
            if relation_actor.team_ids
            else false()
        ),
    }
    for key, spec in registries.relations_for("item").items():
        if key in _INDEX_RELATION_COLUMNS:
            continue  # mirrored above — and cheaper there
        if not any(relation_contains(outer, key) for outer in held):
            continue  # this actor could never be covered by it — don't compile
        rebound = _rebind_to_index(spec.where(relation_actor))
        if rebound is None:
            if key not in _unmirrorable_warned:
                _unmirrorable_warned.add(key)
                logger.warning(
                    "search: item relation @%s cannot be compiled over search_index "
                    "(its where-form reaches %s beyond the id anchor) — search "
                    "narrows to the relations the mirror carries, so rows it alone "
                    "would grant are not findable",
                    key,
                    _RELATION_SOURCE_TABLE,
                )
            continue
        clauses[key] = rebound
    return clauses


async def _relation_index_clause(session: AsyncSession, user: User):
    """The RADD-817 row filter compiled over the index mirror: per-project arms,
    None when @any holds everywhere (the common case)."""
    from sqlalchemy import and_, false, or_

    from radd.modules.auth.types import relation_contains

    per_project = await authz.readable_projects(session, user)
    constrained: dict[uuid.UUID, frozenset[str]] = {}
    for pid, perms in per_project.items():
        relations = authz.relations_held(perms, Permission.ITEM_READ)
        if authz.RELATION_ANY in relations:
            continue
        constrained[pid] = relations
    if not constrained:
        return None
    # The canonical actor (RADD-830 subject graph, memoised) — the same one the
    # list path hands to `spec.where`, so search cannot resolve "my teams"
    # differently from the filter it is supposed to agree with.
    relation_actor = await authz.relation_actor(session, user)
    held_anywhere = {relation for relations in constrained.values() for relation in relations}
    clauses = _relation_clauses(relation_actor, held_anywhere)
    arms = []
    unconstrained = [pid for pid in per_project if pid not in constrained]
    if unconstrained:
        arms.append(SearchIndexRow.project_id.in_(unconstrained))
    for pid, relations in constrained.items():
        # The chain closure (any ⊃ team ⊃ own), same as the canonical resolvers.
        covered = [
            clause
            for key, clause in clauses.items()
            if any(relation_contains(held, key) for held in relations)
        ]
        arms.append(
            and_(
                SearchIndexRow.project_id == pid,
                or_(*covered) if covered else false(),
            )
        )
    return arms[0] if len(arms) == 1 else or_(*arms)


async def search(
    session: AsyncSession,
    user: User,
    q: str,
    *,
    limit: int = 20,
) -> list[SearchHit]:
    q = q.strip()[:MAX_QUERY_CHARS]
    if not q:
        return []
    readable = await _readable_project_ids(session, user)
    if not readable:
        return []
    relation_clause = await _relation_index_clause(session, user)

    # RADD-1085: ts_headline reads the INDEX row's description + public comment
    # text, bypassing the spec-50 builtin blanking the item read applies. When
    # ANY read grant restricts `description` anywhere, non-admin hits degrade
    # to title-only rather than leak — the denied_slq_fields stance: restriction
    # is rare, a per-hit authz pass is not worth it, and a leak is worse than a
    # missing preview.
    snippets_allowed = authz.is_instance_admin(user)
    if not snippets_allowed:
        _, restricted_builtins = await fields_service.outbound_restricted_keys(session)
        snippets_allowed = "description" not in restricted_builtins

    hits: list[SearchHit] = []
    seen: set[uuid.UUID] = set()

    pattern = key_pattern(q)
    if pattern is not None:
        stmt = _scope(
            select(SearchIndexRow).where(SearchIndexRow.key.ilike(pattern)),
            readable,
            relation_clause,
        ).order_by(func.length(SearchIndexRow.key), SearchIndexRow.key).limit(limit)
        for row in (await session.execute(stmt)).scalars():
            hits.append(_hit(row, snippet=None))
            seen.add(row.item_id)

    fts_rows: list[tuple[SearchIndexRow, str | None]] = []
    tsquery_text = build_tsquery(q)
    if tsquery_text:
        tsquery = func.to_tsquery(SEARCH_TS_CONFIG, tsquery_text)
        snippet = func.ts_headline(
            SEARCH_TS_CONFIG,
            SearchIndexRow.description + literal(" ") + SearchIndexRow.comments_text,
            tsquery,
            text("'MaxWords=18, MinWords=6, MaxFragments=1'"),
        )
        stmt = (
            _scope(
                select(SearchIndexRow, snippet).where(SearchIndexRow.tsv.op("@@")(tsquery)),
                readable,
                relation_clause,
            )
            .order_by(
                func.ts_rank_cd(SearchIndexRow.tsv, tsquery).desc(),
                SearchIndexRow.updated_at.desc(),
            )
            .limit(limit + len(seen))
        )
        fts_rows = [(row, headline) for row, headline in (await session.execute(stmt)).all()]

    # The hybrid half (spec 103): fuse FTS ranks with vector-ANN ranks by RRF.
    # Key-shaped queries mean "take me to TD-123", not meaning — skip those.
    semantic_ids: list[uuid.UUID] = []
    if pattern is None and len(q) >= MIN_SEMANTIC_QUERY_CHARS:
        semantic_ids = await _semantic_ids(session, q, readable)

    if not semantic_ids:
        for row, headline in fts_rows:
            if row.item_id in seen or len(hits) >= limit:
                continue
            hits.append(_hit(row, snippet=headline if snippets_allowed else None))
        return hits

    rows_by_id = {row.item_id: (row, headline) for row, headline in fts_rows}
    fused = fusion.rrf_fuse([[row.item_id for row, _ in fts_rows], semantic_ids])
    missing = [item_id for item_id, _ in fused if item_id not in rows_by_id]
    if missing:
        extra = await session.execute(
            _scope(
                select(SearchIndexRow).where(SearchIndexRow.item_id.in_(missing)),
                readable,
                relation_clause,
            )
        )
        for row in extra.scalars():
            # Semantic-only hits carry a description excerpt instead of a
            # ts_headline (there may be zero keyword overlap to highlight).
            rows_by_id[row.item_id] = (
                row,
                (row.description[:_SIMILAR_SNIPPET_CHARS] or None) if snippets_allowed else None,
            )
    for item_id, _score in fused:
        if item_id in seen or len(hits) >= limit:
            continue
        pair = rows_by_id.get(item_id)
        if pair is None:
            continue
        hits.append(_hit(pair[0], snippet=pair[1] if snippets_allowed else None))
        seen.add(item_id)
    return hits


async def _semantic_ids(
    session: AsyncSession, q: str, readable: set[uuid.UUID]
) -> list[uuid.UUID]:
    """Vector candidates via the ai module's seam — deferred + feature-detected
    (the deflect/DOCS_MODULE precedent, direction reversed), time-budgeted, and
    empty on ANY failure so /search never degrades below pure FTS."""
    from .types import AI_EMBEDDINGS_MODULE

    if AI_EMBEDDINGS_MODULE not in settings.modules:
        return []
    from radd.modules.ai.embeddings import candidates

    try:
        if not await candidates.semantic_enabled(session):
            return []
        ranked = await asyncio.wait_for(
            candidates.item_candidates(
                session, q, project_ids=list(readable), limit=SEMANTIC_CANDIDATES
            ),
            timeout=settings.ai_search_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 — FTS-only beats a 500 (incl. timeout)
        logger.warning("semantic search skipped: %s", exc.__class__.__name__)
        return []
    return [item_id for item_id, _distance in ranked]


def _hit(row: SearchIndexRow, *, snippet: str | None) -> SearchHit:
    return SearchHit(
        item_id=row.item_id,
        project_id=row.project_id,
        key=row.key,
        title=row.title,
        snippet=snippet,
    )


# --- similarity seam (spec 46: the AI module's FTS-first duplicate candidates) ---

# Caps for similar_to_text: input text, OR-ed query tokens, description excerpt.
_SIMILAR_TEXT_CHARS = 2000
_SIMILAR_MAX_TOKENS = 32
_SIMILAR_SNIPPET_CHARS = 240


async def similar_to_text(
    session: AsyncSession,
    text: str,
    *,
    user: User | None = None,
    exclude_item_id: uuid.UUID | None = None,
    limit: int = 10,
) -> list[tuple[SearchHit, float]]:
    """Items ranked by full-text overlap with `text` (spec 46).

    Unlike `search` (which ANDs terms for precision), the tokens are OR-ed so
    partial overlap still ranks — ts_rank_cd rewards documents sharing more
    terms. When `user` is given, results are scoped to projects where they hold
    item.read (the same rule as `search`). Returns (hit, rank) pairs ordered by
    rank descending; rank is the raw ts_rank_cd value (callers normalize), and
    `snippet` carries a plain description excerpt (no highlighting).
    """
    tokens = TSQUERY_TOKEN_RE.findall(text[:_SIMILAR_TEXT_CHARS])
    deduped: list[str] = []
    seen_tokens: set[str] = set()
    for token in tokens:
        lowered = token.lower()
        if lowered not in seen_tokens:
            seen_tokens.add(lowered)
            deduped.append(token)
    if not deduped:
        return []
    tsquery = func.to_tsquery(
        SEARCH_TS_CONFIG, " | ".join(f"'{token}'" for token in deduped[:_SIMILAR_MAX_TOKENS])
    )
    rank = func.ts_rank_cd(SearchIndexRow.tsv, tsquery)
    stmt = (
        select(SearchIndexRow, rank)
        .where(SearchIndexRow.tsv.op("@@")(tsquery))
        .order_by(rank.desc(), SearchIndexRow.updated_at.desc())
        .limit(limit)
    )
    if exclude_item_id is not None:
        stmt = stmt.where(SearchIndexRow.item_id != exclude_item_id)
    if user is not None:
        readable = await _readable_project_ids(session, user)
        if not readable:
            return []
        stmt = stmt.where(SearchIndexRow.project_id.in_(readable))
        clause = await _relation_index_clause(session, user)
        if clause is not None:
            stmt = stmt.where(clause)
    return [
        (_hit(row, snippet=row.description[:_SIMILAR_SNIPPET_CHARS] or None), float(value))
        for row, value in (await session.execute(stmt)).all()
    ]


async def titles_for_keys(
    session: AsyncSession, keys: list[str], *, user: User
) -> list[tuple[str, str]]:
    """(key, title) for the keys the actor can read, input-ordered. The
    similar-reasons stream re-resolves the client's visible rows here rather
    than trusting client-supplied titles into an LLM prompt; unreadable or
    unknown keys silently drop out."""
    if not keys:
        return []
    readable = await _readable_project_ids(session, user)
    if not readable:
        return []
    stmt = select(SearchIndexRow.key, SearchIndexRow.title).where(
        SearchIndexRow.key.in_(keys), SearchIndexRow.project_id.in_(readable)
    )
    clause = await _relation_index_clause(session, user)
    if clause is not None:
        stmt = stmt.where(clause)
    rows = await session.execute(stmt)
    titles = dict(rows.all())
    return [(key, titles[key]) for key in keys if key in titles]


# --- the ai-embedder seam (spec 103) ------------------------------------------


@dataclass(frozen=True)
class EmbeddingRow:
    item_id: uuid.UUID
    project_id: uuid.UUID
    key: str
    title: str
    description: str
    comments_text: str


async def rows_for_embedding(
    session: AsyncSession,
    *,
    item_ids: list[uuid.UUID] | None = None,
    missing_from: str | None = None,
    model: str = "",
    limit: int = 200,
) -> list[EmbeddingRow]:
    """Text rows for the semantic-search embedder (spec 103).

    Reuses this table because search already solved "public text only" —
    internal comment bodies never enter `search_index`, so they can never reach
    an embedding provider either. Two modes: explicit `item_ids` (event-driven
    re-embeds), or `missing_from` — the embedder's (table, model) anti-join for
    the reconcile sweep, run HERE so each module queries only its own table
    shape (the other side is referenced by name, which is the seam's contract).
    """
    if item_ids is not None:
        stmt = (
            select(SearchIndexRow).where(SearchIndexRow.item_id.in_(item_ids)).limit(limit)
        )
        rows = (await session.execute(stmt)).scalars()
        return [_embedding_row(row) for row in rows]
    if missing_from is None:
        raise ValueError("pass item_ids or missing_from")
    if not missing_from.isidentifier():
        raise ValueError(f"unusable table name: {missing_from!r}")
    result = await session.execute(
        text(
            "SELECT si.item_id, si.project_id, si.key, si.title, si.description,"
            " si.comments_text FROM search_index si"
            f" LEFT JOIN {missing_from} e ON e.item_id = si.item_id AND e.model = :model"
            " WHERE e.item_id IS NULL ORDER BY si.updated_at DESC LIMIT :limit"
        ),
        {"model": model, "limit": limit},
    )
    return [
        EmbeddingRow(
            item_id=item_id,
            project_id=project_id,
            key=key,
            title=title,
            description=description,
            comments_text=comments_text,
        )
        for item_id, project_id, key, title, description, comments_text in result.all()
    ]


def _embedding_row(row: SearchIndexRow) -> EmbeddingRow:
    return EmbeddingRow(
        item_id=row.item_id,
        project_id=row.project_id,
        key=row.key,
        title=row.title,
        description=row.description,
        comments_text=row.comments_text,
    )
