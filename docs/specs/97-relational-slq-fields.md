# Spec 97 — Relational SLQ fields (`logged_by`, `commented_by`)

Phase 1 of "search issues by what happened to them, not just what they are".

## The question

"Which issues has Alice logged time on?" and "which issues has she commented
on?" are questions about WORKLOGS and COMMENTS whose answer is a set of ITEMS.
Until now SLQ could only ask about an item's own columns and its custom fields,
so those questions had no expression at all.

## The mechanism (no new machinery)

Spec 94 already built the seam: `SlqFieldSpec` in the kernel, registered on a
plugin manifest, resolved by `items/slq/compiler.py::_plugin_condition`, which
wraps the plugin's `Select` of work-item ids as `work_item.id IN (…)` and
applies negation itself. Its docstring already said the resolver "builds the
subquery from the plugin's OWN table only" — which is exactly the decoupling a
relational field needs.

So this spec adds **no new extension point**. It uses the existing one from two
new places:

| Field | Module | Subquery over |
|---|---|---|
| `logged_by` | `timelogging` | `worklogs` (+ the `auth.User` spine to name a person) |
| `commented_by` | `comments` | `comments` (+ `auth.User`) |

Items learns nothing about worklogs or comments; each module owns its own
predicate and its own table. That is the whole point of registering rather than
hardcoding — `items/slq/builtins.py` importing `timelogging.models` would have
been a rule-1 violation dressed up as a feature.

```
logged_by = me
logged_by = "alice@corp.example"
logged_by ~ alice                  -- substring over name OR email
logged_by != me                    -- negation applied by the engine
logged_by = me AND commented_by = me
```

## The one contract change: `me`

`me` is a grammar SENTINEL, not a string — the parser marks it unquoted and
`helpers.plain()` deliberately REJECTS it, because most fields have no meaning
for it. Plugin resolvers previously received `(contains, value)` and so could
never honour it.

`SlqFieldSpec.item_ids` now takes `(contains, value, ctx: SlqFieldContext)`,
where the context carries `current_user_id` and an `is_me` flag set when the
operand was the bare sentinel. A resolver branches on the flag instead of
text-matching, so `logged_by = me` and a person literally named "me" can't be
confused.

This is a breaking change to the plugin SLQ contract. Nothing external ships
against it; the three in-repo registrations (two tests, the `acme-notes`
example) were updated in the same change. Passing a context object rather than
the id itself means the next thing a resolver wants — a project scope, a
timezone — is an added attribute, not another signature break.

## Semantics worth stating

- **Itemless worklogs never match.** Spec-59 rows have `item_id IS NULL`, so
  they cannot name an item. The resolver filters that explicitly rather than
  relying on the join to drop them.
- **`commented_by` matches on authorship alone.** An internal comment (spec 50
  per-team visibility) can therefore make its item match for someone who could
  not read that comment. The item is still subject to normal project/item RBAC,
  so this leaks the EXISTENCE of a comment by a person, never its content.
  Narrowing it needs the actor's team set in `SlqFieldContext`; deliberately
  deferred rather than half-done.
- **Operators are `=`, `!=`, `~`** — the plugin-field surface. `IN (a, b)` would
  need the registry contract to accept a value list; not required by the ask.

## Tests

`tests/test_relational_slq.py` executes the compiled queries against real rows
rather than asserting on SQL strings: a wrong predicate in query compilation
returns a plausible-looking set rather than an error, so the only honest check
is which ids come back. Covers `me` (and that it is per-actor), email, substring,
negation, the itemless case, and composition of the two fields with each other.

## Not in this phase

- **A worklog SLQ dialect** for the timesheet (filter worklogs by author /
  category / issue). The lexer and parser are generic, but the field catalog,
  `Context`, builtins, compiler, suggest and ordering are all item-shaped, so
  this is a parallel dialect sharing only the front half.
- **Sub-queries** (`issue IN (state = Done)` inside a worklog query). Feasible
  once both dialects exist — the item compiler already yields a
  `ColumnElement[bool]` that drops straight into a subquery — but it needs
  grammar support for a nested query as an operand.
- **Value autocomplete** for the new fields. They appear in field-name
  completion (`helpers.field_names` already folds in the registry), but suggest
  has no per-plugin-field value resolver.
