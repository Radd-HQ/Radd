"""What a code-host connector declares (RADD-1435). A connector owns its payload
parser, its API walker and this spec; vcs runs everything the hosts have in common
— the rows, their administration and audit, env seeding, webhook authentication,
the backfill harness and the receiver's tail — parameterised by it. The plugin
provides the spec on the `VcsSocket.CONNECTOR` socket, so a disabled connector
leaves Settings → Version control."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from radd.config import settings

from ..triggers import ConnectorTriggers
from ..types import ConnectorSetting, DeliveryCredential, VcsProvider

if TYPE_CHECKING:
    from .backfill import BackfillRun


@dataclass(frozen=True)
class HostWording:
    """What the connector's tab on Settings → Version control says."""

    title: str
    description: str
    #: Where to register the webhook on the host, shown in the empty state.
    webhook_path: str
    name_placeholder: str
    base_url_placeholder: str
    token_hint: str
    secret_hint: str
    #: What a merged change is called on this host.
    change_noun: str
    #: What the audit log calls a repository ("project" on GitLab).
    repo_noun: str = "repository"
    #: Set: the base URL is optional and defaults to this public host.
    default_base_url: str = ""
    #: The tab's position among the connectors.
    order: int = 0


@dataclass(frozen=True)
class Probe:
    """The connection test's one request, and how a success reads."""

    url: str
    label: Callable[[Any], str]  # the JSON body → the line the admin sees


@dataclass(frozen=True)
class Paging:
    """How the host's REST API pages a list."""

    #: The page-size query parameter (`limit` on Forgejo, `per_page` elsewhere).
    size_param: str
    #: A header naming the next page (GitLab's `X-Next-Page`); "" = short page ends it.
    next_page_header: str = ""


@dataclass(frozen=True)
class ConnectorSpec:
    provider: VcsProvider
    wording: HostWording
    connection_model: type
    repo_model: type
    #: The six audited administration events (CONNECTION_CREATED … REPO_DELETED).
    events: type[StrEnum]
    #: CONNECTION / REPO: the audited entity types and the NotFound/Conflict names.
    entities: type[StrEnum]
    #: The connector's own automation triggers (RADD-1309), fired by `vcs.receiving`.
    triggers: ConnectorTriggers
    credential: DeliveryCredential
    #: (raw body, the delivery's credential header, one connection's secret) → verified.
    authenticate: Callable[[bytes, str, str], bool]
    #: The repository path a webhook payload names ("" when it names none).
    repo_name: Callable[[dict], str]
    #: The connection test's request; None = the connection cannot be tested yet.
    #: (The API base and headers are the connection row's `api_url`/`api_headers`.)
    probe: Callable[[Any], Probe | None]
    #: The history walk (branches, merge/pull requests, commits) the backfill runs.
    walk: Callable[["BackfillRun"], Awaitable[None]]
    paging: Paging

    def setting(self, key: ConnectorSetting) -> Any:
        """The connector's `config.Settings` value `<provider>_<key>` — env seeds
        and tunables share one naming rule across connectors. A connector without
        the key (Forgejo seeds no token) reads empty."""
        return getattr(settings, f"{self.provider.value}_{key.value}", "")
