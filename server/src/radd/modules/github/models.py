"""GitHub hosts and their repositories as rows (RADD-1129); the env secret only seeds
one. The columns are the connector kit's (`vcs.connector_kit.columns`)."""

from radd import secretbox
from radd.db import Base
from radd.modules.vcs.connector_kit.columns import ConnectionColumns, RepoColumns

from .types import GITHUB_COM, GITHUB_COM_API


class GithubConnection(ConnectionColumns, Base):
    """One GitHub host — github.com, or a GitHub Enterprise Server. It signs
    webhook bodies with its secret (`X-Hub-Signature-256`)."""

    __tablename__ = "github_connections"

    @property
    def api_url(self) -> str:
        """api.github.com for github.com, `<host>/api/v3` for Enterprise Server —
        derived, so an admin enters one URL."""
        web = (self.base_url or GITHUB_COM).rstrip("/")
        return GITHUB_COM_API if web == GITHUB_COM else f"{web}/api/v3"

    @property
    def api_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.api_token:  # the one place the token is decrypted (RADD-1446)
            headers["Authorization"] = f"Bearer {secretbox.decrypt(self.api_token)}"
        return headers


class GithubRepo(RepoColumns, Base):
    __tablename__ = "github_repos"
    __connection_table__ = "github_connections"
