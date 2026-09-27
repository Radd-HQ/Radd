"""Forgejo/Gitea hosts and their repositories as rows (spec 111); the env secret only
seeds one. The columns are the connector kit's (`vcs.connector_kit.columns`)."""

from radd import secretbox
from radd.db import Base
from radd.modules.vcs.connector_kit.columns import ConnectionColumns, RepoColumns


class ForgejoConnection(ConnectionColumns, Base):
    """One Forgejo/Gitea host; it signs webhook bodies with HMAC-SHA256."""

    __tablename__ = "forgejo_connections"

    @property
    def api_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/v1"

    @property
    def api_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_token:  # the one place the token is decrypted (RADD-1446)
            headers["Authorization"] = f"token {secretbox.decrypt(self.api_token)}"
        return headers


class ForgejoRepo(RepoColumns, Base):
    __tablename__ = "forgejo_repos"
    __connection_table__ = "forgejo_connections"
