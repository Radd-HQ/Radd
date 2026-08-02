import uuid
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class Form(Base, TimestampMixin):
    """Template-scoped intake form (spec 17): captures structured input and creates a
    work item in `project_id`.

    `fields` is an ordered list of `{field_key, label_override?, help?, required}` dicts —
    each `field_key` references a registry field definition in the project's scope
    (validated on write). A form field may be `required` even when the underlying
    registry field is not. `defaults` is a `FormDefaults` dict applied to the item the
    submit creates (kind/state_name/priority/labels/assignee_email/cycle_name/
    release_version); unknown state/label/cycle/release names are stored verbatim and
    resolved at submit, an unknown assignee is rejected on write.

    Public path (spec 62): `allow_public` opens the tokened, no-login submit route
    `/public/forms/{public_token}`; the token is minted the first time public is
    enabled and KEPT on disable, so re-enabling restores the same link.
    """

    __tablename__ = "forms"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    defaults: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    title_prompt: Mapped[str] = mapped_column(String(200), default="Summary")
    # The ITEM-description area on the submit page (distinct from `description`,
    # the form's own blurb). Enabled by default; required is a per-form choice.
    description_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    description_prompt: Mapped[str] = mapped_column(
        String(200), default="Description", server_default="Description"
    )
    description_required: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Public submit path (spec 62): token minted on first enable, kept on disable.
    allow_public: Mapped[bool] = mapped_column(Boolean, default=False)
    public_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)


class FormShare(Base, TimestampMixin):
    """One portal grant on a form (spec 73): exactly one of user_id / team_id
    (the item_participants CHECK idiom). Presence = the subject SEES the form on
    the requester portal AND may SUBMIT it — no levels (editing stays
    `form.manage`). Rows die with the form/user/team (FK CASCADE); user-merge
    dedupes via auth `_MERGE_DEDUPE` on (form_id, user_id)."""

    __tablename__ = "form_shares"
    __table_args__ = (
        # Naming convention prefixes ck_<table>_ — final name ck_form_shares_one_subject.
        CheckConstraint(
            "(user_id IS NULL) != (team_id IS NULL)",
            name="one_subject",
        ),
        UniqueConstraint("form_id", "user_id"),
        UniqueConstraint("form_id", "team_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    form_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forms.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
