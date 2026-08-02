import uuid

from pydantic import BaseModel, ConfigDict, Field

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


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    created_at: UtcDatetime
    # The CURRENT user's effective permissions on the project (Permission values),
    # hydrated by the router via auth.authz. Plain strings: projects loads before
    # auth in the module assembly, so schemas here must not import auth.
    permissions: list[str] = Field(default_factory=list)
