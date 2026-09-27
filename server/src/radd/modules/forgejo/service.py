"""Forgejo's connector spec and its rows through the vcs connector kit: a delivery
is signed (HMAC-SHA256 of the raw body, `X-Forgejo-Signature`/`X-Gitea-Signature`)
with its connection's secret."""

import hashlib
import hmac

from radd.modules.vcs.connector_kit import github_shape
from radd.modules.vcs.connector_kit.spec import ConnectorSpec, HostWording, Paging, Probe
from radd.modules.vcs.connector_kit.store import ConnectorStore
from radd.modules.vcs.triggers import ConnectorTriggers
from radd.modules.vcs.types import DeliveryCredential, VcsProvider

from . import backfill
from .models import ForgejoConnection, ForgejoRepo
from .types import ForgejoEntity, ForgejoEvent, ForgejoTrigger


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Constant-time check of the hex HMAC-SHA256 a delivery carries against a
    connection's secret."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _probe(connection: ForgejoConnection) -> Probe | None:
    if not connection.base_url:
        return None
    return Probe(f"{connection.api_url}/version", lambda body: str(body.get("version", "")))


CONNECTOR = ConnectorSpec(
    provider=VcsProvider.FORGEJO,
    wording=HostWording(
        title="Forgejo",
        description=(
            "Hosts whose pushes, branches and pull requests link themselves to issues by key. Map a repository"
            " to a project to make it the project its release triggers name. For a repository with “Mirror"
            " time” switched on, time tracked on a pull request is copied into the linked issue, dated by when"
            " it was added."
        ),
        webhook_path="/api/v1/integrations/forgejo",
        name_placeholder="Forgejo",
        base_url_placeholder="https://git.example.com",
        secret_hint="The shared secret the host signs payloads with.",
        token_hint="Read-only. Needed for backfill, the connection test and tracked-time mirroring.",
        change_noun="pull request",
        order=10,
    ),
    connection_model=ForgejoConnection,
    repo_model=ForgejoRepo,
    events=ForgejoEvent,
    entities=ForgejoEntity,
    triggers=ConnectorTriggers(
        host="Forgejo",
        change="pull request",
        opened=ForgejoTrigger.PR_OPENED,
        merged=ForgejoTrigger.PR_MERGED,
        closed=ForgejoTrigger.PR_CLOSED,
        updated=ForgejoTrigger.PR_UPDATED,
        pushed=ForgejoTrigger.PUSHED,
        release_published=ForgejoTrigger.RELEASE_PUBLISHED,
        ci_completed=ForgejoTrigger.CI_COMPLETED,
    ),
    credential=DeliveryCredential.SIGNATURE,
    authenticate=verify_signature,
    repo_name=github_shape.repo_full_name,
    probe=_probe,
    walk=backfill.walk,
    paging=Paging(size_param="limit"),
)

store = ConnectorStore(CONNECTOR)
