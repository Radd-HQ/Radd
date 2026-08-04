# Relations — normative resolution semantics (RADD-823)

This table is the algebra deny (RADD-819) slots into. It is written **before**
deny exists, deliberately: an algebra defined in prose grows exceptions, and
deny would otherwise be specified against behaviour instead of rules. The
property test in `server/tests/test_relation_semantics.py` executes every row.

## Syntax (normative)

`resource.action@relation` — e.g. `item.update@team`, `attachment.delete@own`.
The dotted form (`comment.delete.own`) that appears in audit §5.2 is the same
concept in a rejected notation; §5.2 is to be read with `@` substituted. An
**unqualified atom means `@any`**: `item.update ≡ item.update@any`, which is
what makes migration free — every existing role keeps exactly what it had.

## The two axes, and the one composition rule

| Axis | Answers | Carried by | Vocabulary |
|---|---|---|---|
| **Scope** (RADD-814) | *where* | the **grant** | `global ⊃ {project \| space}` |
| **Relation** (RADD-823) | *which rows* | the **atom** | `any ⊃ team ⊃ own` (+ resource extensions) |

The composition rule — the only one there is:

```
allowed(actor, atom, row, at_scope) =
    scope_satisfied(grant.scope, at_scope)          # the RADD-814 ladder
  ∧ relation_satisfied(atom.relation, actor, row)   # this spec
```

Neither term reads the other. "HR sees only HR's issues on the HR project" is
`role[item.read@team]` granted **on that project**; the instance-wide version
is the same role granted globally — the breadth changed, the rule did not. Any
future concept that would need one axis to consult the other means the axes
were factored wrong.

## The relation lattice

A **chain**, widest first: `any ⊃ team ⊃ own`. Containment is normative for
resolution, not a claim about set inclusion of rows: holding `@team` **covers**
the `@own` rows too (the resolvers close downward), because a person trusted
with their team's records is trusted with their own. A relation outside the
chain (a resource-specific extension) is incomparable: it contains only
itself, and `any` contains it.

The **meet** (used by the spec-113 token-scope intersection) is the narrower
of two comparable relations; incomparable relations meet at nothing — the pair
grants nothing, which is the fail-closed direction for a key.

| held \ needed | any | team | own |
|---|---|---|---|
| **any** | ✓ | ✓ | ✓ |
| **team** | ✗ | ✓ | ✓ |
| **own** | ✗ | ✗ | ✓ |

## The two enforcement forms

Every relation declares BOTH, with no defaults (`RelationSpec`):

| Form | Question | Used by | Failure if omitted |
|---|---|---|---|
| `where(actor)` | *which rows?* — a SQL boolean expression | lists, counts, boards, reports, search, SLQ, MCP | every aggregate leaks |
| `holds(actor, row)` | *this row?* — a predicate on a loaded object | write gates, single-item reads, child surfaces | edit-then-error, or a leak through a child |

A pair that disagrees is a silent leak; the contract test asserts they select
the same rows on a fixture. `relation_filter` returns `None` for `@any`
(unconstrained), the OR of the covered specs' clauses otherwise, and `false()`
when nothing is held or the qualifier is unregistered — an empty answer
**excludes** rows.

## Resolution, end to end

Given an actor's effective permission set `P` (post-expansion, post token-scope
narrowing) and a base atom `B` checked at scope `S` against row `R`:

1. **Scope** resolves first, exactly as before relations existed: `P` is
   already the union of grants whose scope satisfies `S` (the RADD-814 ladder).
2. `relations_held(P, B)` → the qualifiers held for `B`. Empty = not held at
   all: refuse (403) or filter to nothing, per surface.
3. `@any` present → unconstrained. Done.
4. Otherwise: **filtering** surfaces AND `relation_filter(resource, held,
   actor)` into the query; **gating** surfaces ask `relation_holds_row`.
5. **Child content inherits the parent's answer** (trap 1): a child surface
   (comments, worklogs, history, watchers, …) resolves its parent through
   `items.service.require_readable_item` and never re-implements steps 2–4.

## Field grants compose (D10)

A field grant qualified by a relation (`write Priority @assigned`) applies the
SAME rule at the field layer: the spec-92 grant decides *whether the field is
restricted and to whom*, and the relation qualifies *for which rows* the grant
satisfies it. Step 4's verdict is computed per (field, row) with the field
grant's relation in place of the atom's. No new machinery: the relation
resolvers are the same two functions.

## Token scopes (spec 113) are lattice-aware

`effective = resolved(account) ∩ scope(key)` meets per-base at the narrower
relation:

| key carries | account holds | effective |
|---|---|---|
| `item.read` | `item.read@team` | `item.read@team` |
| `item.read@team` | `item.read` | `item.read@team` |
| `item.read@own` | `item.read@team` | `item.read@own` |
| `item.read@x` (incomparable) | `item.read@team` | — nothing |

## Deliberately not here

- **`@others`** is the *absence* of `@any`, not a grantable relation. It
  becomes meaningful only beside deny (RADD-819), where `deny item.update@others`
  legitimately carves a hole in a broad grant.
- **Relations are computed; spec-92 grants are explicit.** An issue is "mine"
  structurally (a column); a view is shared by a deliberate act (a grant row).
  Collapsing them means a grant row per issue, which does not survive 503k items.

## Deny (RADD-819) — the rule it slots in with

`access_grants.effect` ∈ {allow, deny}, opt-in (no row carries deny until an
admin writes one). Resolution: **specificity first, deny on ties.**

| pair (same subject, same access) | verdict |
|---|---|
| deny and allow at EQUAL scope | deny |
| project-scoped deny vs global allow | deny (narrower wins) |
| project-scoped allow vs global deny | allow (narrower wins) |
| one deny row, nobody else named | that subject refused; a default-open resource stays open for everyone else |

A deny binds its EXACT access. On an implied route (write satisfies read), a
deny of write blocks that route without closing the check sideways: an open
read stays open, but write no longer answers for read. The one documented back
door — the instance admin — lives at the resolvers' callers, never in the
algebra. Executed by `tests/test_deny_precedence.py`.
