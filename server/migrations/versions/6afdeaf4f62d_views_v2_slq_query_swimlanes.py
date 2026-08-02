"""views v2: SLQ query text + swimlanes (spec 10)

Replaces the structured `filters` JSONB with SLQ query text and adds the
`swimlane_by` axis:

- ADD `query` TEXT NOT NULL DEFAULT '', `swimlane_by` TEXT NULL; `group_by`
  widens to TEXT (axis tokens now include `cf.<key>`).
- CONVERT every stored ViewFilters document into equivalent SLQ (state ids ->
  names, assignee ids -> emails, team ids -> names; multiple values -> IN (...);
  the `none` sentinel -> IS EMPTY). Each conversion is logged; an unresolvable
  reference drops that clause, never the view.
- DROP `filters`.

Downgrade is lossy: SLQ text has no general ViewFilters equivalent, so filters
comes back as '{}' and cf.* axes are cleared.

Revision ID: 6afdeaf4f62d
Revises: fa2747459c4b

"""
import json
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '6afdeaf4f62d'
down_revision = 'fa2747459c4b'
branch_labels = None
depends_on = None

# --- frozen wire values at this revision (migrations must not import app code) ---

NONE_SENTINEL = 'none'  # ViewFilters' "relation unset" literal
# SLQ barewords per the spec-10 lexer; anything else (or a reserved word) gets quoted.
BAREWORD_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.@+/-]*$')
RESERVED_WORDS = frozenset(
    {'and', 'or', 'not', 'in', 'is', 'empty', 'order', 'by', 'asc', 'desc', 'me', 'none',
     'true', 'false'}
)
# Builtin SLQ field names: a custom-field key shadowed by one cannot be expressed.
BUILTIN_FIELDS = frozenset(
    {'project', 'state', 'category', 'kind', 'priority', 'assignee', 'team', 'label',
     'title', 'key', 'parent', 'number', 'created', 'updated'}
)


def _quote(value: str) -> str:
    if BAREWORD_RE.match(value) and value.lower() not in RESERVED_WORDS:
        return value
    escaped = value.replace('\\', '\\\\').replace("'", "\\'")
    return f"'{escaped}'"


def _clause(field: str, values: list[str]) -> str:
    if len(values) == 1:
        return f'{field} = {_quote(values[0])}'
    return f"{field} IN ({', '.join(_quote(v) for v in values)})"


def _relation_clause(field: str, names: list[str], include_none: bool) -> str:
    """assignee/team: names OR the none sentinel -> IS EMPTY."""
    if names and include_none:
        return f'({_clause(field, names)} OR {field} IS EMPTY)'
    if include_none:
        return f'{field} IS EMPTY'
    return _clause(field, names)


def _convert(filters: dict, lookups: dict[str, dict[str, str]]) -> tuple[str, list[str]]:
    """One ViewFilters document -> (SLQ text, dropped-clause notes)."""
    clauses: list[str] = []
    dropped: list[str] = []

    def resolve(kind: str, ids: list) -> list[str]:
        resolved = []
        for raw in ids:
            name = lookups[kind].get(str(raw))
            if name is None:
                dropped.append(f'{kind} {raw} not found')
            else:
                resolved.append(name)
        return resolved

    state_names = resolve('state', filters.get('states') or [])
    if state_names:
        clauses.append(_clause('state', state_names))
    for field, key in (('category', 'categories'), ('kind', 'kinds'), ('priority', 'priorities')):
        values = [str(v) for v in filters.get(key) or []]
        if values:
            clauses.append(_clause(field, values))
    for field, key, kind in (('assignee', 'assignees', 'user'), ('team', 'teams', 'team')):
        raw = [str(v) for v in filters.get(key) or []]
        include_none = NONE_SENTINEL in raw
        names = resolve(kind, [v for v in raw if v != NONE_SENTINEL])
        if names or include_none:
            clauses.append(_relation_clause(field, names, include_none))
    labels = [str(v) for v in filters.get('labels') or []]
    if labels:
        clauses.append(_clause('label', labels))
    for key, value in (filters.get('custom_fields') or {}).items():
        if key in BUILTIN_FIELDS or key.lower() in RESERVED_WORDS or not BAREWORD_RE.match(key):
            dropped.append(f"custom field '{key}' cannot be an SLQ field name")
            continue
        clauses.append(f'{key} = {_quote(str(value))}')
    return ' AND '.join(clauses), dropped


def upgrade() -> None:
    op.add_column('views', sa.Column('query', sa.Text(), server_default='', nullable=False))
    op.add_column('views', sa.Column('swimlane_by', sa.Text(), nullable=True))
    op.alter_column(
        'views', 'group_by',
        existing_type=sa.VARCHAR(length=20), type_=sa.Text(), existing_nullable=True,
    )

    connection = op.get_bind()
    lookups = {
        'state': {
            str(row[0]): row[1]
            for row in connection.execute(sa.text('SELECT id, name FROM states'))
        },
        'user': {
            str(row[0]): row[1]
            for row in connection.execute(sa.text('SELECT id, email FROM users'))
        },
        'team': {
            str(row[0]): row[1]
            for row in connection.execute(sa.text('SELECT id, name FROM teams'))
        },
    }
    views = connection.execute(sa.text('SELECT id, name, filters FROM views ORDER BY created_at'))
    print('views v2: converting stored filters to SLQ')
    for view_id, name, filters in views:
        query, dropped = _convert(filters or {}, lookups)
        connection.execute(
            sa.text('UPDATE views SET query = :query WHERE id = :id'),
            {'query': query, 'id': view_id},
        )
        print(f'  view {view_id} ({name!r}): {json.dumps(filters)} -> {query!r}')
        for note in dropped:
            print(f'    ! dropped clause: {note}')

    op.drop_column('views', 'filters')


def downgrade() -> None:
    # Lossy: SLQ text cannot be mapped back to ViewFilters; views keep no filters.
    op.add_column(
        'views',
        sa.Column(
            'filters', postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"), nullable=False,
        ),
    )
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE views SET group_by = NULL WHERE group_by IS NOT NULL AND "
                "(group_by LIKE 'cf.%' OR length(group_by) > 20)")
    )
    op.alter_column(
        'views', 'group_by',
        existing_type=sa.Text(), type_=sa.VARCHAR(length=20), existing_nullable=True,
    )
    op.drop_column('views', 'swimlane_by')
    op.drop_column('views', 'query')
