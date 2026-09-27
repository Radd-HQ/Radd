"""Per-connector automation triggers (RADD-1309). Each connector owns its trigger
enum (so disabling it removes them); `ConnectorTriggers` builds their catalog
entries with one wording, and every emit goes through `emit_ref`/`emit_release`.
Ref events fire ONCE PER LINKED ISSUE with the item as subject; the release event
is itemless, with the repository's default project as subject when set.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import EventTypeSpec
from radd.modules.events import service as events

from .connector_kit.changes import MrChangeField
from .models import ItemVcsLink
from .types import CiOutcome, VcsEntity


class RefAction(StrEnum):
    """What happened to a merge/pull request; UPDATED = an edit or new commits (`changes`)."""

    OPENED = "opened"
    MERGED = "merged"
    CLOSED = "closed"
    UPDATED = "updated"


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
            "connection_id": {"type": "string", "description": "The configured host connection; distinguish identical repository paths on different hosts"},
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
    ci_completed: StrEnum

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
                            "field": {"type": "string", "enum": [f.value for f in MrChangeField]},
                            "from": {}, "to": {},
                        }},
                        "description": (
                            "What changed: {field, from, to} per field, only for "
                            + ", ".join(f.value for f in MrChangeField)
                            + ' — "commits" (old → new sha) when new commits were pushed; a side the host did not send is omitted'
                        ),
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
            item_event(
                self.ci_completed,
                "workflow / pipeline finished",
                _schema(
                    ref=_REF_SCHEMA,
                    ci={
                        "type": "object",
                        "properties": {
                            "state": {"type": "string", "enum": [o.value for o in CiOutcome]},
                            "url": {"type": "string"},
                            "name": {"type": "string", "description": "Workflow or pipeline name; this event is one run, not required-check approval"},
                            "sha": {"type": "string"},
                            "run_id": {"type": "integer"},
                        },
                    },
                ),
            ),
        ]
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
        payload={"provider": provider, "repo": repo, "connection_id": str(link.connection_id) if link.connection_id else None, **payload, "author": author_facts},
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
    connection_id: uuid.UUID | None = None,
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
            "connection_id": str(connection_id) if connection_id else None,
            "version": version,
            "tag": tag,
            "name": name or version,
            "notes": notes,
            "url": url,
        },
    )


def version_from_tag(tag: str) -> str:
    """`v0.6.1` -> `0.6.1`: releases are stored bare and looked up exactly, so a
    verbatim tag once minted a duplicate release (RADD-707). Only a leading v/V
    before a digit is stripped."""
    tag = tag.strip()
    return tag[1:] if len(tag) > 1 and tag[0] in "vV" and tag[1].isdigit() else tag
