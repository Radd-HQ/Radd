"""The channel resolver and its rule rows (spec 118).

Two halves, and the first is the important one.

**The defaults ARE the acceptance bar.** A rewrite of a notification preference
model is one migration away from silently changing what lands in a thousand
mailboxes, and "nobody noticed" is not evidence — a person who stops receiving
something has nothing to notice. So the first section asserts, kind by kind,
that a user with ZERO rule rows resolves to exactly what RADD-686 gave them:
every kind in the inbox, `DEFAULT_EMAIL_TYPES` also mailed as they happen, and
the three kinds spec 118 introduced off everywhere. It is compared against
`DEFAULT_EMAIL_TYPES` rather than a copied list precisely so that widening that
set later cannot pass here while quietly changing behaviour.

The second section is precedence, which is where a scoped model earns its
keep — most specific wins, rules are sparse, and a subscription is not a scope
until someone actually holds one.
"""

import importlib.util
import uuid
from enum import StrEnum
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.notify import prefs as prefs_read, rules as policy, service as notify_service
from radd.modules.notify.kinds import (
    NOTIFICATION_KINDS,
    PERSONAL_KINDS,
    SUBSCRIPTION_ONLY_KINDS,
    every_kind,
)
from radd.modules.notify.router import put_preferences
from radd.modules.notify.rules import Relation, RuleRow, RuleSet, Subject
from radd.modules.notify.schemas import NotificationPrefsUpdate, NotificationRuleWrite
from radd.modules.notify.types import (
    DEFAULT_EMAIL_TYPES,
    Channel,
    NotificationType,
    RuleScope,
)
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

PROJECT = uuid.uuid4()
SPACE = uuid.uuid4()
TEAM = uuid.uuid4()

WATCHING = Relation(is_participating=True)
MINE = Relation(is_own=True)


def _rules(*rows: tuple[RuleScope, uuid.UUID | None, dict[NotificationType, Channel]]) -> RuleSet:
    return RuleSet.of(
        [
            RuleRow(scope, scope_id, {k.value: c.value for k, c in channels.items()})
            for scope, scope_id, channels in rows
        ]
    )


# --- the vocabulary is total ---------------------------------------------------


def test_the_kind_vocabulary_covers_the_enum_exactly():
    """`NOTIFICATION_KINDS` is not a list of the kinds someone remembered.

    `DEFAULT_MATRIX` is BUILT from it, so a `NotificationType` with no row here
    has no default anywhere — and the lookup that wants one runs inside
    `create_notification`, i.e. inside the consumer's per-event SAVEPOINT, which
    logs the failure and skips the event. The notification would never arrive and
    nothing would say so: exactly the shape of RADD-978 and RADD-1056, both of
    which survived for months behind a log line nobody reads.

    Asserted as SET EQUALITY in both directions on purpose. `>=` would let a
    stale row for a deleted member sit in the settings page forever, and `<=`
    would let a new member ship with no row at all — the two failures are
    different and only one of them is loud.
    """
    assert {spec.kind for spec in NOTIFICATION_KINDS} == set(NotificationType)
    assert len(NOTIFICATION_KINDS) == len(set(every_kind()))  # and each listed once


def test_a_kind_the_vocabulary_does_not_know_degrades_instead_of_raising():
    """The version where somebody adds an enum member and forgets the row.

    `kinds.is_personal` documents the conservative answer — an unknown kind is
    treated as own-directed, so it still reaches the person the producer
    addressed — and until this test that promise ended in a KeyError two lines
    later, swallowed by the SAVEPOINT. A stand-in enum is the only way to reach
    it: the test above guarantees no real member can.
    """

    class _FutureKind(StrEnum):
        TELEPATHY = "telepathy"

    verdict = policy.resolve(_FutureKind.TELEPATHY, policy.EMPTY, MINE)

    assert verdict.scope is RuleScope.OWN
    assert verdict.inbox is True and verdict.inherited is True


# --- the defaults reproduce RADD-686 exactly ----------------------------------


@pytest.mark.parametrize("kind", every_kind(), ids=lambda k: k.value)
def test_no_rules_reproduces_the_pre_spec_118_answer(kind: NotificationType):
    """Every kind, both relationships, against the constant that decided it before.

    `own` and `participating` answer alike on purpose: RADD-686's preference had
    no notion of relation, so the mailer gave a watcher and an assignee the same
    answer, and any difference introduced here would be a behaviour change for
    someone who never asked for one.
    """
    relation = MINE if kind in PERSONAL_KINDS else WATCHING
    verdict = policy.resolve(kind, policy.EMPTY, relation)

    if kind in SUBSCRIPTION_ONLY_KINDS:
        assert verdict.channel is Channel.OFF
        return
    assert verdict.inbox is True
    assert verdict.email is (kind in DEFAULT_EMAIL_TYPES)
    assert verdict.inherited is True


def test_the_new_kinds_are_off_in_every_relationship_scope():
    """`created`/`updated`/`page_created` exist for subscribers. An instance that
    never opens the settings page must not start receiving a class of
    notification it has never had — so the only way to see one is to ask."""
    for kind in SUBSCRIPTION_ONLY_KINDS:
        for relation in (MINE, WATCHING, Relation(in_my_teams=True)):
            assert policy.resolve(kind, policy.EMPTY, relation).channel is Channel.OFF


def test_the_my_teams_column_starts_silent():
    """The one genuinely NEW reach in the spec. Defaulting it on would subscribe
    every member of a team to their whole team's traffic on deploy day."""
    relation = Relation(in_my_teams=True)
    for spec in NOTIFICATION_KINDS:
        if spec.personal:
            continue  # personal kinds ignore relations entirely — see below
        assert policy.resolve(spec.kind, policy.EMPTY, relation).channel is Channel.OFF


def test_a_personal_kind_ignores_the_relationship_entirely():
    """An approver is frequently neither the assignee nor a watcher. Resolving
    `approval` through a relationship scope would have handed them `off` and
    ended approvals in silence — which is why personal kinds resolve through
    `own` alone whatever the caller says the relation is."""
    stranger = Relation()  # no relation at all

    verdict = policy.resolve(NotificationType.APPROVAL, policy.EMPTY, stranger)

    assert verdict.scope is RuleScope.OWN
    assert verdict.inbox and verdict.email


def test_an_ambient_kind_with_no_relation_at_all_is_silent():
    """The other side of the same coin: nothing connects this person to the
    subject, so no scope applies and there is nothing to inherit."""
    verdict = policy.resolve(NotificationType.COMMENTED, policy.EMPTY, Relation())
    assert verdict.channel is Channel.OFF and verdict.scope is None


# --- precedence and sparseness ------------------------------------------------


def test_own_beats_participating():
    rules = _rules(
        (RuleScope.OWN, None, {NotificationType.COMMENTED: Channel.BOTH}),
        (RuleScope.PARTICIPATING, None, {NotificationType.COMMENTED: Channel.OFF}),
    )

    verdict = policy.resolve(
        NotificationType.COMMENTED, rules, Relation(is_own=True, is_participating=True)
    )

    assert verdict.channel is Channel.BOTH and verdict.scope is RuleScope.OWN


def test_a_rule_is_sparse_and_falls_through_to_the_next_scope():
    """Subscribing to a project to hear about new issues must not overwrite what
    you already said about comments — so a rule states only what it has an
    opinion about, and the kinds it is silent on keep falling through."""
    rules = _rules(
        (RuleScope.OWN, None, {NotificationType.STATE_CHANGED: Channel.OFF}),
        (RuleScope.PARTICIPATING, None, {NotificationType.COMMENTED: Channel.EMAIL}),
    )
    relation = Relation(is_own=True, is_participating=True)

    assert policy.resolve(NotificationType.STATE_CHANGED, rules, relation).channel is Channel.OFF
    commented = policy.resolve(NotificationType.COMMENTED, rules, relation)
    assert commented.channel is Channel.EMAIL and commented.scope is RuleScope.PARTICIPATING


def test_an_unset_kind_inherits_the_FIRST_applicable_scopes_default():
    """Not the last, and not a global default. That is what makes "I subscribed
    to a project" mean "and everything about my own issues is unchanged": the
    project's `off` default sits BELOW `own` in the order and never surfaces."""
    rules = _rules((RuleScope.PROJECT, PROJECT, {NotificationType.CREATED: Channel.INBOX}))

    verdict = policy.resolve(
        NotificationType.COMMENTED, rules, MINE, Subject(project_id=PROJECT)
    )

    assert verdict.scope is RuleScope.OWN
    assert verdict.inherited and verdict.inbox


def test_a_project_you_have_not_subscribed_to_is_not_a_scope():
    """An unsubscribed project is not a scope with an empty opinion — it is not
    in the order at all. Otherwise its `off` default would swallow the
    `participating` answer sitting underneath it, and watching an issue would
    stop working in every project nobody had subscribed to."""
    order = policy.applicable_scopes(policy.EMPTY, WATCHING, Subject(project_id=PROJECT))
    assert order == ((RuleScope.PARTICIPATING, None),)

    with_row = _rules((RuleScope.PROJECT, PROJECT, {NotificationType.CREATED: Channel.INBOX}))
    assert policy.applicable_scopes(with_row, WATCHING, Subject(project_id=PROJECT)) == (
        (RuleScope.PARTICIPATING, None),
        (RuleScope.PROJECT, PROJECT),
    )


def test_a_team_subscription_outranks_the_my_teams_column():
    """Naming a team is a choice; belonging to one is a circumstance. The
    specific answer wins, which is the whole ordering rule in one case."""
    rules = _rules(
        (RuleScope.TEAM, TEAM, {NotificationType.CREATED: Channel.BOTH}),
        (RuleScope.TEAMS, None, {NotificationType.CREATED: Channel.OFF}),
    )

    verdict = policy.resolve(
        NotificationType.CREATED,
        rules,
        Relation(in_my_teams=True),
        Subject(team_id=TEAM),
    )

    assert verdict.channel is Channel.BOTH and verdict.scope is RuleScope.TEAM


def test_email_without_inbox_is_expressible():
    """The state RADD-686 could not reach. A muted type never became a row and
    the mailer mailed rows, so "email me, do not clutter my inbox" was
    structurally unsayable; moving the decision onto the row's columns is what
    makes the fourth cell state real."""
    rules = _rules((RuleScope.OWN, None, {NotificationType.ASSIGNED: Channel.EMAIL}))

    verdict = policy.resolve(NotificationType.ASSIGNED, rules, MINE)

    assert verdict.email is True and verdict.inbox is False and verdict.silent is False


def test_a_channel_value_this_version_does_not_know_falls_through():
    """A hand-written API call or a member removed in a later version. The
    consumer runs in a background loop, so a preference that cannot be parsed
    has to read as a preference that was not expressed, not as a 500."""
    rules = RuleSet.of(
        [
            RuleRow(RuleScope.OWN, None, {NotificationType.COMMENTED.value: "carrier-pigeon"}),
            RuleRow(
                RuleScope.PARTICIPATING,
                None,
                {NotificationType.COMMENTED.value: Channel.OFF.value},
            ),
        ]
    )

    verdict = policy.resolve(
        NotificationType.COMMENTED, rules, Relation(is_own=True, is_participating=True)
    )

    assert verdict.channel is Channel.OFF and verdict.scope is RuleScope.PARTICIPATING


# --- storage: normalisation and the migration ---------------------------------


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, name: str, *, admin: bool = False) -> User:
    user = User(
        email=f"rules-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=(InstanceRole.ADMIN if admin else InstanceRole.MEMBER).value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project(db, name: str):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"NR{uuid.uuid4().hex[:4].upper()}", name=name)
    )
    await db.flush()
    return project


def _load_migration(name: str):
    """Import one revision file by name — `migrations/` is a script directory,
    not a package, so there is nothing to import normally."""
    path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_a_rule_row_must_match_its_scope_shape(db):
    """The model's one invariant: a subscription names a target, a relationship
    does not. A row that gets it wrong is DROPPED rather than stored — a stored
    one could never be matched by the resolver, so it would be a preference
    silently doing nothing, which is the failure this whole spec came from."""
    user = await _user(db, "Malformed")

    await notify_service.set_rules(
        db,
        user.id,
        [
            (RuleScope.OWN, PROJECT, {NotificationType.COMMENTED.value: "off"}),
            (RuleScope.PROJECT, None, {NotificationType.COMMENTED.value: "off"}),
            (RuleScope.PARTICIPATING, None, {NotificationType.COMMENTED.value: "off"}),
        ],
    )

    stored = await notify_service.list_rules(db, user.id)
    assert [(row.scope, row.scope_id) for row in stored] == [
        (RuleScope.PARTICIPATING.value, None)
    ]


async def test_saving_an_empty_matrix_leaves_no_rows_and_therefore_the_defaults(db):
    """Resetting every cell has to land back on "no opinion", not on a row full
    of nothing — otherwise "restore defaults" would store a rule that shadows
    the defaults it claims to restore."""
    user = await _user(db, "Reset")
    await notify_service.set_rules(
        db, user.id, [(RuleScope.OWN, None, {NotificationType.COMMENTED.value: "off"})]
    )

    await notify_service.set_rules(db, user.id, [(RuleScope.OWN, None, {})])

    assert await notify_service.list_rules(db, user.id) == []
    resolved = await notify_service.rules_by_user(db, [user.id])
    assert policy.resolve(NotificationType.COMMENTED, resolved[user.id], WATCHING).inbox


async def test_a_subscription_names_only_a_target_the_actor_may_read(db):
    """A `scope_id` is a uuid the CLIENT picks, so the API checks it.

    Delivery was never the exposure — every notification still passes
    `consumer._allowed`, so a rule pointing at a project you cannot read delivers
    nothing. The READ is: it resolves each target's name for display, so storing
    an arbitrary uuid and reading it back was a lookup service for the key and
    name of every project on the instance.

    Dropped rather than 4xx'd, because a PUT is a full replace: refusing the
    request over one bad subscription would refuse the matrix edit the person
    actually made. The response is read back off the rows, so what did not
    survive is visibly gone.
    """
    member = await _user(db, "Member")
    admin = await _user(db, "Admin", admin=True)
    project = await _project(db, "Closed")
    body = NotificationPrefsUpdate(
        rules=[
            NotificationRuleWrite(
                scope=RuleScope.PROJECT,
                scope_id=project.id,
                channels={NotificationType.CREATED: Channel.INBOX},
            ),
            NotificationRuleWrite(
                scope=RuleScope.OWN,
                scope_id=None,
                channels={NotificationType.COMMENTED: Channel.OFF},
            ),
        ],
        email_digest=True,
    )

    stored = await put_preferences(body, db, member)

    # The matrix row survives; the subscription to a project they cannot see does not.
    assert [(rule.scope, rule.scope_id) for rule in stored.rules] == [(RuleScope.OWN, None)]
    # The control, and the important half: the SAME request from someone who can
    # read that project keeps it, so the assertion above is the gate rather than
    # a save that stores nothing.
    kept = await put_preferences(body, db, admin)
    assert (RuleScope.PROJECT, project.id) in [(rule.scope, rule.scope_id) for rule in kept.rules]


async def test_the_preferences_read_will_not_NAME_a_target_you_cannot_read(db):
    """The same gate from the other side, and why it is applied twice.

    A stored row outlives the access that created it: someone removed from a
    project keeps the subscription row until their next save. Until then the read
    must not narrate it — so it comes back label-less and the page shows the row
    as unavailable, which is also the honest rendering for a target that has been
    deleted. From here the two are the same fact.
    """
    member = await _user(db, "Member")
    admin = await _user(db, "Admin", admin=True)
    project = await _project(db, "Closed")
    for user in (member, admin):
        await notify_service.set_rules(
            db, user.id, [(RuleScope.PROJECT, project.id, {"created": "inbox"})]
        )

    (theirs,) = [rule for rule in (await prefs_read.read(db, member)).rules if rule.scope_id]
    (visible,) = [rule for rule in (await prefs_read.read(db, admin)).rules if rule.scope_id]

    assert theirs.scope_id == project.id and theirs.scope_label is None
    assert visible.scope_label is not None and project.key in visible.scope_label


async def test_subscriber_lookup_finds_every_target_family_in_one_query(db):
    """Fan-out's question. A row's CHANNELS are deliberately not consulted here:
    narrowing by "…and the row turns something on" would be a second copy of the
    resolver written in SQL, and the two would drift the first time precedence
    changed."""
    subscriber = await _user(db, "Subscriber")
    stranger = await _user(db, "Stranger")
    await notify_service.set_rules(
        db,
        subscriber.id,
        [
            (RuleScope.PROJECT, PROJECT, {NotificationType.CREATED.value: "inbox"}),
            (RuleScope.SPACE, SPACE, {NotificationType.PAGE_UPDATED.value: "off"}),
        ],
    )
    await notify_service.set_rules(
        db, stranger.id, [(RuleScope.PROJECT, uuid.uuid4(), {"created": "inbox"})]
    )

    found = await notify_service.subscriber_ids(db, project_id=PROJECT, space_id=SPACE)

    assert found == {subscriber.id}
    assert await notify_service.subscriber_ids(db) == set()


async def test_the_migration_carries_a_stored_preference_into_own_and_participating(db):
    """The behaviour-preservation promise, run rather than described.

    A pre-spec-118 `notification_prefs` row is written back (the columns are
    gone at head, so they are re-added first) and the migration's own
    `upgrade()` is replayed through alembic's operations proxy — inside the test
    transaction, which rolls the DDL back too, so no other test sees a table
    mid-migration. Postgres DDL being transactional is what makes this honest
    instead of destructive.

    Two things are asserted, and the second matters more: a muted type becomes
    `off` and an emailed one becomes `both`, AND the `teams` column is left
    empty. Writing the same preference into my-teams would have subscribed every
    existing user to their whole team's traffic on the strength of a checkbox
    they ticked about their own issues.
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = _load_migration("d118notifrules_scoped_notification_rules")
    user_id = uuid.uuid4()
    await db.execute(text("DROP TABLE notification_rules"))
    await db.execute(
        text(
            "ALTER TABLE notification_prefs "
            "ADD COLUMN muted_types jsonb NOT NULL DEFAULT '[]'::jsonb, "
            "ADD COLUMN email_types jsonb NOT NULL DEFAULT '[]'::jsonb"
        )
    )
    await db.execute(
        text(
            "INSERT INTO notification_prefs (user_id, muted_types, email_types, email_digest) "
            "VALUES (:user_id, '[\"state_changed\"]'::jsonb, '[\"assigned\"]'::jsonb, true)"
        ),
        {"user_id": user_id},
    )

    def _upgrade(connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    await db.run_sync(lambda session: _upgrade(session.connection()))

    rows = await db.execute(
        text(
            "SELECT scope, scope_id, channels FROM notification_rules "
            "WHERE user_id = :user_id ORDER BY scope"
        ),
        {"user_id": user_id},
    )
    carried = {scope: channels for scope, _scope_id, channels in rows.all()}
    assert set(carried) == {RuleScope.OWN.value, RuleScope.PARTICIPATING.value}
    for channels in carried.values():
        assert channels["state_changed"] == "off"  # muted → off
        assert channels["assigned"] == "both"  # emailed → both
        assert channels["commented"] == "inbox"  # neither → inbox
        # The kinds spec 118 introduced are absent, so they fall through to
        # their `off` default like everyone else's.
        assert not SUBSCRIPTION_ONLY_KINDS & {NotificationType(k) for k in channels}
