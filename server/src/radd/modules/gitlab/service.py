"""GitLab's connector spec and its rows through the vcs connector kit. GitLab does
not sign bodies: the hook's secret comes back as `X-Gitlab-Token`, compared
constant-time against each active connection's."""

import hmac

from radd.modules.vcs.connector_kit.spec import ConnectorSpec, HostWording, Paging, Probe
from radd.modules.vcs.connector_kit.store import ConnectorStore
from radd.modules.vcs.triggers import ConnectorTriggers
from radd.modules.vcs.types import DeliveryCredential, VcsProvider

from . import backfill, parsing
from .models import GitlabConnection, GitlabRepo
from .types import GITLAB_COM, GitlabEntity, GitlabEvent, GitlabTrigger

#: The next-page header GitLab's offset paging answers (empty on the last page).
NEXT_PAGE_HEADER = "X-Next-Page"


def verify_token(provided: str, secret: str) -> bool:
    """Constant-time check of the `X-Gitlab-Token` header against a hook secret.
    An empty secret verifies nothing — a connection with no secret is not a
    connection that accepts every body."""
    if not secret or not provided:
        return False
    return hmac.compare_digest(provided.strip(), secret)


def _probe(connection: GitlabConnection) -> Probe:
    """With a token: `GET /version`. Without: a one-row public project listing,
    proving the API host answers."""
    if connection.api_token:
        return Probe(f"{connection.api_url}/version", lambda body: f"GitLab {body.get('version', '?')}")
    return Probe(f"{connection.api_url}/projects?per_page=1", lambda _body: connection.api_url)


CONNECTOR = ConnectorSpec(
    provider=VcsProvider.GITLAB,
    wording=HostWording(
        title="GitLab",
        description=(
            "Hosts whose pushes, branches and merge requests link themselves to issues by key (the key in a"
            " branch name, a commit message or a merge request title). For a repository with “Mirror time”"
            " switched on, time logged on a merge request with /spend is copied into the linked issue's"
            " worklogs, and the backfill imports that history once."
        ),
        webhook_path=(
            "/api/v1/integrations/gitlab (project or group hook; triggers: push, merge request, pipeline,"
            " deployment, releases; paste the same secret token here)"
        ),
        name_placeholder="GitLab",
        base_url_placeholder="https://gitlab.example.com",
        default_base_url=GITLAB_COM,
        secret_hint="The hook's Secret token; GitLab sends it back on every delivery (X-Gitlab-Token).",
        token_hint=(
            "A read_api token. Needed for backfill, the connection test and time mirroring; an administrator's"
            " token also matches authors by email automatically."
        ),
        change_noun="merge request",
        repo_noun="project",
        order=30,
    ),
    connection_model=GitlabConnection,
    repo_model=GitlabRepo,
    events=GitlabEvent,
    entities=GitlabEntity,
    triggers=ConnectorTriggers(
        host="GitLab",
        change="merge request",
        opened=GitlabTrigger.MR_OPENED,
        merged=GitlabTrigger.MR_MERGED,
        closed=GitlabTrigger.MR_CLOSED,
        updated=GitlabTrigger.MR_UPDATED,
        pushed=GitlabTrigger.PUSHED,
        release_published=GitlabTrigger.RELEASE_PUBLISHED,
        ci_completed=GitlabTrigger.CI_COMPLETED,  # RADD-1255
    ),
    credential=DeliveryCredential.TOKEN,
    authenticate=lambda _raw_body, token, secret: verify_token(token, secret),
    repo_name=parsing.project_path,
    probe=_probe,
    walk=backfill.walk,
    paging=Paging(size_param="per_page", next_page_header=NEXT_PAGE_HEADER),
)

store = ConnectorStore(CONNECTOR)
