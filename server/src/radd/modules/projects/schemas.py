import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from radd.apitypes import UtcDatetime


class InstanceConfigRead(BaseModel):
    """Safe instance config for authenticated clients (spec 35)."""

    work_week_days: list[str]
    timelog_hours_per_day: int  # global scalar; days-per-week stays env-only
    timelog_days_per_week: int
    sso_enabled: bool = False  # spec 40 — the login page shows the SSO button
    ldap_enabled: bool = False  # spec 42 — the login page offers directory sign-in
    #: Spec 121 — the principal rows' fixed ids, so the SPA can name "Anyone
    #: on the web" as a share subject without hardcoding a wire constant.
    anyone_id: uuid.UUID | None = None
    signed_in_id: uuid.UUID | None = None


class ProjectCreate(BaseModel):
    key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9]{0,9}$", description="Short key, e.g. TD")
    name: str = Field(min_length=1, max_length=200)


class ProjectUpdate(BaseModel):
    """PATCH /projects/{id} (RADD-1009): rename and describe; omitted = unchanged.
    The KEY is deliberately absent: every item key, issue URL and connector regex
    derives from it, so a renamed key would orphan all of them at once."""

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
    #: RADD-1041 — presentation only: "entitled" | "related" (see authz.ProjectVia),
    #: feeding the sidebar's related-projects preference; never a filter. None on
    #: POST's response. A string because projects cannot import auth's enum.
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


class BlockerRead(BaseModel):
    """RADD-1174: one thing that stops a project being deleted. The SPA prints
    `label`, and `hint` as a link to `url` — the owner's page for that row, from
    its declared entity links (RADD-1378); None when it declares none."""

    kind: str
    id: str
    label: str
    hint: str = ""
    url: str | None = None


class ProjectContentRead(BaseModel):
    """`GET /projects/{id}/content` (RADD-1174): what deleting the project
    destroys (`counts`, keyed by the owners' nouns — `items`, `comments`,
    `attachments`, `worklogs`, `worklog_seconds`, …) and what forbids it."""

    counts: dict[str, int]
    blockers: list[BlockerRead]
