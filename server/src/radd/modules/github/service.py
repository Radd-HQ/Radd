"""GitHub's connector spec and its rows through the vcs connector kit: a delivery is
signed (`X-Hub-Signature-256: sha256=<hex>` of the raw body) with its connection's
secret."""

import hashlib
import hmac

from radd.modules.vcs.connector_kit import github_shape
from radd.modules.vcs.connector_kit.spec import ConnectorSpec, HostWording, Paging, Probe
from radd.modules.vcs.connector_kit.store import ConnectorStore
from radd.modules.vcs.triggers import ConnectorTriggers
from radd.modules.vcs.types import DeliveryCredential, VcsProvider

from . import backfill
from .models import GithubConnection, GithubRepo
from .types import GITHUB_COM, GithubEntity, GithubEvent, GithubTrigger

_SIGNATURE_PREFIX = "sha256="


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Constant-time check of `X-Hub-Signature-256: sha256=<hex>` against a
    shared secret. A bare hex digest is accepted too, so a proxy that strips the
    prefix does not silently break every delivery."""
    if not secret or not signature:
        return False
    provided = signature.strip().removeprefix(_SIGNATURE_PREFIX)
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


def _probe(connection: GithubConnection) -> Probe:
    """With a token: `GET /user`, reporting the login the token belongs to.
    Without: `GET /meta`, proving the API host answers."""
    if connection.api_token:
        return Probe(f"{connection.api_url}/user", lambda body: f"user {body.get('login')}")
    return Probe(f"{connection.api_url}/meta", lambda _body: connection.api_url)


CONNECTOR = ConnectorSpec(
    provider=VcsProvider.GITHUB,
    wording=HostWording(
        title="GitHub",
        description=(
            "Repositories whose pushes, branches, pull requests and check runs link themselves to issues by key."
            " Map a repository to a project to make it the project its release triggers name. GitHub has no"
            " time tracking, so a pull-request comment carries it: “/spend 1h30”, “/spend 45m 2026-09-18"
            " note”, “/spend 1h KEY-12” to log to another issue, “/unspend” to forget yours on that PR — copied"
            " into the linked issue by the mapped account, for a repository with “Mirror time” switched on."
        ),
        webhook_path=(
            "/api/v1/integrations/github (content type application/json, events: push, pull requests,"
            " releases, check suites, workflow runs)"
        ),
        name_placeholder="GitHub",
        base_url_placeholder="https://github.com",
        default_base_url=GITHUB_COM,
        secret_hint="The secret entered on the webhook; GitHub signs every delivery with it (X-Hub-Signature-256).",
        token_hint=(
            "Read-only. A fine-grained token with Contents and Pull requests read access; needed for backfill"
            " and the connection test."
        ),
        change_noun="pull request",
        order=20,
    ),
    connection_model=GithubConnection,
    repo_model=GithubRepo,
    events=GithubEvent,
    entities=GithubEntity,
    triggers=ConnectorTriggers(
        host="GitHub",
        change="pull request",
        opened=GithubTrigger.PR_OPENED,
        merged=GithubTrigger.PR_MERGED,
        closed=GithubTrigger.PR_CLOSED,
        updated=GithubTrigger.PR_UPDATED,
        pushed=GithubTrigger.PUSHED,
        release_published=GithubTrigger.RELEASE_PUBLISHED,
        ci_completed=GithubTrigger.CI_COMPLETED,
    ),
    credential=DeliveryCredential.SIGNATURE,
    authenticate=verify_signature,
    repo_name=github_shape.repo_full_name,
    probe=_probe,
    walk=backfill.walk,
    paging=Paging(size_param="per_page"),
)

store = ConnectorStore(CONNECTOR)
