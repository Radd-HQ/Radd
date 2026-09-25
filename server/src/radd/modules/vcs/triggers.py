"""Per-connector automation triggers (RADD-1309).

A connector LINKS refs and mirrors time. It does nothing else on its own: what
happens when a merge request is merged, a branch is pushed, CI finishes or a
release is published is an automation someone switches on. Before this, every
receiver ended by moving the issues a merged MR named to the waiting-for-release
state, and GitHub/Forgejo swept a published release — with no switch.

Each connector OWNS its trigger vocabulary (its own StrEnum, registered by its
own plugin), so disabling GitLab removes GitLab's triggers from the automation
palette. What they share lives here, so the three agree on the payload an
automation reads: the `EventTypeSpec`s are built from one `ConnectorTriggers`,
and every emit goes through `emit_ref` / `emit_release`.

Ref events are emitted ONCE PER LINKED ISSUE with the item as subject, which is
what lets an item action (`set_state`, `add_comment`, …) act on the issue the
merge request names. The release event is itemless; its subject is the
repository's default project when one is set, so `gate.project` works on it.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import EventTypeSpec
from radd.kernel import changes as kchanges
from radd.modules.events import service as events

from .models import ItemVcsLink
from .types import VcsEntity


class RefAction(StrEnum):
    """What happened to a merge/pull request, as the trigger names it. RADD-1330
    added UPDATED: an edit (`update`/`edited`) or new commits (`synchronize`),
    carrying WHICH fields changed in the payload's `changes`."""

    OPENED = "opened"
    MERGED = "merged"
    CLOSED = "closed"
    UPDATED = "updated"


#: The `changes` entry an update carries when new commits were pushed to the
#: request (GitLab `oldrev`, GitHub `synchronize`, Forgejo `synchronized`).
COMMITS_CHANGE = "commits"

#: Bookkeeping fields every host stamps on an update — never "what changed".
NOISE_FIELDS: frozenset[str] = frozenset({"updated_at", "updated_by_id", "last_edited_at", "last_edited_by_id"})


def diff_entries(pairs) -> list[dict[str, Any]]:
    """The kernel diff (`[{field, from, to}]`, spec 123) for an update, from
    `(field, old, new)` triples, without the hosts' bookkeeping stamps. The
    kernel shape — not a list of names — because `changes` is what the audit
    ledger, search text and the "field changed" gate already read."""
    out: list[dict[str, Any]] = []
    for field_name, old, new in pairs:
        if str(field_name) in NOISE_FIELDS:
            continue
        entry = kchanges.change(str(field_name), old, new)
        if entry is not None:
            out.append(entry)
    return out


class CiOutcome(StrEnum):
    """The terminal CI states that fire `ci.completed`. A queued or running
    report updates the link's badge and fires nothing."""

    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


_REF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "description": "branch | commit | merge_request | pull_request"},
        "title": {"type": "string"},
        "url": {"type": "string"},
        "status": {"type": "string", "description": "open | merged | closed (merge/pull requests)"},
        "number": {"type": "string", "description": "The merge/pull request's number (!iid / #n)"},
        "source_branch": {"type": "string"},
        "target_branch": {"type": "string"},
    },
}


def _schema(**properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "provider": {"type": "string"},
            "repo": {"type": "string", "description": "The repository's full path, e.g. group/project"},
            **properties,
        },
    }


#: RADD-1320: who acted on the host; `user` (a subject ref) is the Radd person.
_AUTHOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"username": {"type": "string"}, "email": {"type": "string"}},
}


@dataclass(frozen=True)
class ConnectorTriggers:
    """One connector's trigger vocabulary. The connector declares the enum
    members; this turns them into catalog entries with one wording."""

    host: str  # "GitLab" — the palette group and the label prefix
    change: str  # "merge request" / "pull request"
    opened: StrEnum
    merged: StrEnum
    closed: StrEnum
    updated: StrEnum
    pushed: StrEnum
    release_published: StrEnum
    #: None for a host whose CI the connector does not read yet (GitLab: RADD-1255).
    ci_completed: StrEnum | None = None

    def for_action(self, action: RefAction) -> StrEnum:
        return {
            RefAction.OPENED: self.opened,
            RefAction.MERGED: self.merged,
            RefAction.CLOSED: self.closed,
            RefAction.UPDATED: self.updated,
        }[action]

    def specs(self) -> tuple[EventTypeSpec, ...]:
        ref = _schema(action={"type": "string"}, ref=_REF_SCHEMA)

        def item_event(
            event_type: StrEnum, label: str, schema: dict[str, Any], *, diff: bool = False
        ) -> EventTypeSpec:
            schema = {**schema, "properties": {**schema["properties"], "author": _AUTHOR_SCHEMA}}
            return EventTypeSpec(
                event_type, f"{self.host}: {label}", self.host,
                item_scoped=True, subjects=("item", "user"), payload_schema=schema, has_changes=diff,
            )

        change = self.change
        out = [
            item_event(self.opened, f"{change} opened", ref),
            item_event(self.merged, f"{change} merged", ref),
            item_event(self.closed, f"{change} closed without merging", ref),
            item_event(
                self.updated,
                f"{change} updated",
                _schema(
                    action={"type": "string"},
                    ref=_REF_SCHEMA,
                    changes={
                        "type": "array",
                        "items": {"type": "object", "properties": {
                            "field": {"type": "string"}, "from": {}, "to": {},
                        }},
                        "description": 'What changed: {field, from, to} per field (title, description, labels, …); field "commits" (old → new sha) when new commits were pushed',
                    },
                ),
                diff=True,
            ),
            item_event(
                self.pushed,
                "branch or commit pushed",
                _schema(
                    branch={"type": "string"},
                    ref=_REF_SCHEMA,
                    commits={"type": "array", "description": "The pushed commits naming this issue"},
                ),
            ),
        ]
        if self.ci_completed is not None:
            out.append(
                item_event(
                    self.ci_completed,
                    "CI finished",
                    _schema(
                        ref=_REF_SCHEMA,
                        ci={
                            "type": "object",
                            "properties": {
                                "state": {"type": "string", "enum": [o.value for o in CiOutcome]},
                                "url": {"type": "string"},
                            },
                        },
                    ),
                )
            )
        out.append(
            EventTypeSpec(
                self.release_published, f"{self.host}: release published", self.host,
                subjects=("project",),
                payload_schema=_schema(
                    version={"type": "string", "description": "The tag with a leading v stripped"},
                    tag={"type": "string"},
                    name={"type": "string"},
                    notes={"type": "string"},
                    url={"type": "string"},
                ),
            )
        )
        return tuple(out)


@dataclass(frozen=True)
class HostAuthor:
    """Who acted on the host (RADD-1320): the pusher, the person who opened or
    merged the request. Resolved to a Radd user through `vcs_user_links` — the
    identity map the time mirror fills — so a rule can act on the person."""

    connection_id: uuid.UUID | None
    username: str
    email: str = ""


def host_author(payload: dict, connection_id: uuid.UUID | None) -> HostAuthor | None:
    """The acting account from a webhook body, across the three hosts: GitLab
    puts it at `user_username`/`user_email` (push) or `user` (merge request);
    GitHub and Forgejo at `sender` (GitHub hides the email; a push's `pusher`
    carries one)."""
    username = str(payload.get("user_username") or "")
    email = str(payload.get("user_email") or "")
    if not username:
        user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
        username, email = str(user.get("username") or ""), str(user.get("email") or email)
    if not username:
        sender = payload.get("sender") if isinstance(payload.get("sender"), dict) else {}
        pusher = payload.get("pusher") if isinstance(payload.get("pusher"), dict) else {}
        username = str(sender.get("login") or sender.get("username") or "")
        email = str(sender.get("email") or pusher.get("email") or "")
    return HostAuthor(connection_id, username, email) if username else None


async def _author_facts(
    session: AsyncSession, provider: str, author: HostAuthor | None
) -> tuple[dict[str, Any] | None, uuid.UUID | None]:
    if author is None:
        return None, None
    user_id = None
    if author.connection_id is not None:
        from .timemirror import resolve_author  # deferred: timemirror imports this module's siblings
        from .types import VcsProvider

        user_id = await resolve_author(
            session, provider=VcsProvider(provider), connection_id=author.connection_id,
            username=author.username, email=author.email,
        )
    return {"username": author.username, "email": author.email}, user_id


def ref_of(link: ItemVcsLink, **extra: Any) -> dict[str, Any]:
    """The `ref` block every ref event carries: the link as recorded, plus what
    the delivery knew that the link does not store (number, branches)."""
    return {
        "type": link.ref_type,
        "title": link.title,
        "url": link.url,
        "status": link.status,
        **{key: str(value) for key, value in extra.items() if value not in (None, "")},
    }


async def emit_ref(
    session: AsyncSession,
    event_type: StrEnum,
    link: ItemVcsLink,
    *,
    provider: str,
    repo: str,
    actor_id: uuid.UUID | None,
    payload: dict[str, Any],
    author: HostAuthor | None = None,
    changes: list[dict[str, Any]] | None = None,
) -> None:
    """One trigger event about one linked issue. `payload` is the event's own
    data (action, ref, commits, ci); provider/repo are stamped here, and the
    host `author` (RADD-1320) with the Radd `user` it maps to, when it does."""
    author_facts, user_id = await _author_facts(session, provider, author)
    await events.emit(
        session,
        event_type=event_type,
        entity_type=VcsEntity.VCS_LINK,
        entity_id=link.id,
        actor_id=actor_id,
        subjects={"item": link.item_id, "user": user_id},
        payload={"provider": provider, "repo": repo, **payload, "author": author_facts},
        changes=changes,  # RADD-1330: the kernel diff, on "updated" only
    )


async def emit_release(
    session: AsyncSession,
    event_type: StrEnum,
    *,
    entity_type: StrEnum,
    entity_id: object,
    provider: str,
    repo: str,
    project_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    version: str,
    tag: str,
    name: str,
    notes: str,
    url: str,
) -> None:
    """A published release. Itemless; the repository's default project is the
    subject when it has one — the automation decides what, if anything, ships."""
    await events.emit(
        session,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        subjects={"project": project_id} if project_id is not None else None,
        payload={
            "provider": provider,
            "repo": repo,
            "version": version,
            "tag": tag,
            "name": name or version,
            "notes": notes,
            "url": url,
        },
    )


def version_from_tag(tag: str) -> str:
    """`v0.6.1` -> `0.6.1` (RADD-707).

    A git tag and a release VERSION are not the same string: tags are `vX.Y.Z`
    by convention, while every release recorded in the tracker is bare. Release
    lookup is by exact version, so taking the tag verbatim once minted a second
    `v0.6.1` release beside `0.6.1` and swept waiting work into it. Only a
    leading `v` before a digit is stripped — a tag genuinely named something
    else is left alone rather than guessed at. One copy for every connector
    since RADD-1309 (there were three)."""
    tag = tag.strip()
    return tag[1:] if len(tag) > 1 and tag[0] in "vV" and tag[1].isdigit() else tag
