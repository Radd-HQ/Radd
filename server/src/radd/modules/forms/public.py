"""Public (tokened, no-login) form path — spec 62.

Render + submit for `/public/forms/{token}`: submissions run as the SYSTEM
actor through the ordinary submit_form path, the given email resolves to a
registered reporter or becomes the item's mail contact (ack included).

The mailintake seam is a DEFERRED import (mailintake loads after forms in
RADD_MODULES) and feature-detected: with the module disabled, public submits
still work — the requester just isn't addressable afterwards.
"""

import logging
from types import ModuleType

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.fields import service as fields_service
from radd.modules.projects import service as projects_service

from . import service
from .models import Form
from .schemas import (
    FormSubmit,
    PublicDeflectDoc,
    PublicDeflectResponse,
    PublicFormField,
    PublicFormRead,
    PublicFormSubmit,
    PublicSubmitResult,
)
from .types import FormEntity, PUBLIC_DEFLECT_LIMIT

logger = logging.getLogger(__name__)

MAILINTAKE_MODULE = "radd.modules.mailintake"
DOCS_MODULE = "radd.modules.docs"


def _mailintake() -> ModuleType | None:
    """The mailintake service seam, when that module is enabled (deferred —
    mailintake loads after forms; None = contacts/acks silently skipped)."""
    if MAILINTAKE_MODULE not in settings.modules:
        return None
    from radd.modules.mailintake import service as mail_service

    return mail_service


async def _form_by_token(session: AsyncSession, token: str) -> Form:
    """Resolve a PUBLIC link: 404 for an unknown token, 409 for a link whose
    form is currently disabled or no longer public (the token survives)."""
    result = await session.execute(select(Form).where(Form.public_token == token))
    form = result.scalar_one_or_none()
    if form is None:
        raise NotFoundError(FormEntity.FORM, token)
    if not form.allow_public or not form.enabled:
        raise ConflictError(FormEntity.FORM, reason=f"form '{form.name}' is not accepting public submissions")
    return form


async def trimmed_read(session: AsyncSession, form: Form) -> PublicFormRead:
    """The trimmed render payload: form chrome + each exposed field WITH the
    definition bits the widgets need — the visitor (anonymous, or a portal
    sharee — spec 73) may not read the registry."""
    project = await projects_service.get_project(session, form.project_id)
    definitions = {
        definition.key: definition
        for definition in await fields_service.definitions_for_project(session, project)
    }
    fields: list[PublicFormField] = []
    for form_field in form.fields:
        definition = definitions.get(form_field["field_key"])
        if definition is None:
            continue  # dropped from the registry since the form was built
        fields.append(
            PublicFormField(
                field_key=definition.key,
                label=form_field.get("label_override") or definition.name,
                help=form_field.get("help"),
                required=bool(form_field.get("required")),
                type=definition.type,
                options=definition.options,
                display=definition.display,
                default_value=definition.default_value,
            )
        )
    return PublicFormRead(
        name=form.name,
        description=form.description,
        title_prompt=form.title_prompt,
        description_enabled=form.description_enabled,
        description_prompt=form.description_prompt,
        description_required=form.description_required,
        fields=fields,
    )


async def render_public_form(session: AsyncSession, token: str) -> PublicFormRead:
    """GET /public/forms/{token} — the tokened, no-login render."""
    form = await _form_by_token(session, token)
    return await trimmed_read(session, form)


async def deflect_public_form(
    session: AsyncSession, token: str, q: str
) -> PublicDeflectResponse:
    """GET /public/forms/{token}/deflect — top public-KB pages for the visitor's
    half-typed title (spec 74; semantic-fused when the ai module is up, spec
    106). Token-gated exactly like the form itself; ITEMS ARE NOT SEARCHED
    (resolved issues stay internal). The docs seam is a DEFERRED,
    feature-detected import (docs loads after forms in RADD_MODULES);
    module absent/disabled → an empty list, the form still works."""
    await _form_by_token(session, token)
    q = q.strip()
    if not q or DOCS_MODULE not in settings.modules:
        return PublicDeflectResponse(docs=[])
    from radd.modules.docs import public as docs_public

    results = await docs_public.deflect_public(session, q, limit=PUBLIC_DEFLECT_LIMIT)
    if not results:
        return PublicDeflectResponse(docs=[])
    space_names = {
        space.id: space.name for space in await docs_public.list_public_spaces(session)
    }
    return PublicDeflectResponse(
        docs=[
            PublicDeflectDoc(
                id=result.page_id,
                space_id=result.space_id,
                title=result.title,
                space_name=space_names.get(result.space_id, ""),
            )
            for result in results
        ]
    )


async def _resolve_reporter(session: AsyncSession, email: str) -> User | None:
    user = await auth.get_user_by_email(session, email.lower())
    return user if user is not None and user.active else None


async def submit_public_form(
    session: AsyncSession, token: str, data: PublicFormSubmit
) -> PublicSubmitResult:
    """Create the item as the SYSTEM actor through the ordinary submit path.
    The email decides addressability: an active user becomes the reporter
    (auto-watch takes over); anyone else gets a mail_contacts row + an ack."""
    # Deferred: automations loads after forms in RADD_MODULES (and its catalog
    # imports forms.types back) — same idiom as the workspace→settings edge.
    from radd.modules.automations.types import SYSTEM_ACTOR_ID

    form = await _form_by_token(session, token)
    actor = await auth.get_user(session, SYSTEM_ACTOR_ID)
    reporter = await _resolve_reporter(session, data.email)
    item = await service.submit_form(
        session,
        form.id,
        FormSubmit(title=data.title, description=data.description, values=data.values),
        actor,
        reporter_id=reporter.id if reporter is not None else None,
    )
    if reporter is None and (mail_service := _mailintake()) is not None:
        await mail_service.upsert_contact(
            session, item.id, email=data.email, name=data.name
        )
        # The ack is best-effort and self-guarded (SMTP config, mail_send_ack);
        # a pre-commit send is accepted — a stray ack beats extra machinery.
        await mail_service.send_ack(
            email=data.email.lower(), name=data.name, item_key=item.key, title=item.title
        )
    return PublicSubmitResult(key=item.key, title=item.title)
