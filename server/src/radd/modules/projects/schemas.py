import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from radd.apitypes import UtcDatetime


class InstanceConfigRead(BaseModel):
    """Safe instance config for authenticated clients (spec 35)."""

    work_week_days: list[str]
    # Spec 67 follow-up: hours-per-day is a GLOBAL scalar (instance override →
    # env default) — the frontend duration formatter reads it from here instead
    # of hardcoding 8. days-per-week stays env-only (config.timelog_days_per_week).
    timelog_hours_per_day: int
    timelog_days_per_week: int
    sso_enabled: bool = False  # spec 40 — the login page shows the SSO button
    ldap_enabled: bool = False  # spec 42 — the login page offers directory sign-in
    #: Spec 121 — the principal rows' fixed ids, so the SPA can name "Anyone
    #: on the web" as a share subject without hardcoding a wire constant.
    anyone_id: uuid.UUID | None = None
    signed_in_id: uuid.UUID | None = None


class InstanceStatusRead(BaseModel):
    """Non-secret deploy-level status for the instance settings surface (spec 50) —
    instance-admin only. Secrets stay env-only; this is what's ENABLED, not the values."""

    sso_enabled: bool
    ldap_enabled: bool
    # Spec 84: a service (bind) account is configured — gates the AD group/user
    # import + team-sync affordances in the admin UI.
    ldap_bind_account: bool
    smtp_configured: bool
    mfa_available: bool  # TOTP MFA ships enabled (spec 48)
    ai_provider: str  # "" = AI off
    attachment_storage: str  # "filesystem" | "s3"
    workers_enabled: bool
    connectors: dict[str, bool]  # {gitlab, forgejo, google_chat, alertmanager, email_intake}


class ProjectCreate(BaseModel):
    key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9]{0,9}$", description="Short key, e.g. TD")
    name: str = Field(min_length=1, max_length=200)


class ProjectUpdate(BaseModel):
    """PATCH /projects/{id} (RADD-1009): rename and describe.

    The KEY is deliberately absent. Every item key (`TD-1234`) derives from it,
    it is the instance-wide address the connectors' regexes and every issue URL
    carry, and the project counter rides on it — a renamed key would orphan all
    of them at once. Omitted = unchanged.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def _name_has_substance(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    #: RADD-1009 — plain text, "" when the project has never been described.
    description: str = ""
    created_at: UtcDatetime
    # The CURRENT user's effective permissions on the project (Permission values),
    # hydrated by the router via auth.authz. Plain strings: projects loads before
    # auth in the module assembly, so schemas here must not import auth.
    permissions: list[str] = Field(default_factory=list)
    #: RADD-1041 — presentation-only: WHY this row appears in a `GET /projects`
    #: listing. "entitled" = item.read held by grant (theirs whether or not
    #: anything is in it); "related" = item.read held only in qualified form
    #: (own/participant/team) AND a real relationship, e.g. their own filed
    #: ticket. `None` on `POST /projects`'s response, which has no
    #: `visible_projects` lookup behind it. Never a filter: the SET of projects
    #: returned is still exactly `auth.authz.visible_projects` (RADD-937) — this
    #: only feeds the sidebar's "related projects" preference (RADD-1041) so it
    #: can hide the related half without the server hiding anything. Plain
    #: string, not the auth enum (`ProjectVia`): projects loads before auth, so
    #: this file cannot import it — same reason `permissions` above is `str`.
    via: str | None = None
    #: Spec 121 — the two public-access switches, DERIVED from grants: the
    #: Public role held by the Anyone principal here, and the Contributor role
    #: held by Signed-in users. Plain booleans for the chip and the Access
    #: screen; the rows themselves live in `GET /role-grants?project_id=`.
    public: bool = False
    contributions: bool = False


class PublicAccessUpdate(BaseModel):
    """PUT /projects/{id}/public-access (spec 121): the two switches."""

    public: bool
    contributions: bool = False


class ProjectSummaryRead(BaseModel):
    total: int
    related_count: int
    permissions: list[str]
