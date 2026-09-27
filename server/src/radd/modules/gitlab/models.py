"""GitLab hosts and their projects as rows (RADD-1253); the env secret only seeds one.
The columns are the connector kit's (`vcs.connector_kit.columns`); a repository's
`full_name` is GitLab's `path_with_namespace` (`group/subgroup/project`)."""

from radd.db import Base
from radd.modules.vcs.connector_kit.columns import ConnectionColumns, RepoColumns

from .types import GITLAB_COM


class GitlabConnection(ConnectionColumns, Base):
    """One GitLab host — gitlab.com, or a self-managed instance. The hook's
    "Secret token" comes back verbatim as `X-Gitlab-Token` (no HMAC). An ADMIN's
    `read_api` token also exposes other users' emails, which is what makes
    worklog author matching automatic on an LDAP-backed host."""

    __tablename__ = "gitlab_connections"

    @property
    def _web(self) -> str:
        return (self.base_url or GITLAB_COM).rstrip("/")

    @property
    def api_url(self) -> str:
        return f"{self._web}/api/v4"

    @property
    def graphql_url(self) -> str:
        return f"{self._web}/api/graphql"

    @property
    def api_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["PRIVATE-TOKEN"] = self.api_token
        return headers


class GitlabRepo(RepoColumns, Base):
    __tablename__ = "gitlab_repos"
    __connection_table__ = "gitlab_connections"
