import uuid
from fastapi import APIRouter
from sqlalchemy import select
from .config_router import Session, CurrentUser, require_mail_admin
from .models import MailSignatureSettings
from .signatures import SignatureSettings, SignaturePreview, detect
from radd.modules.settings import service as settings
from radd.modules.settings.types import SettingKey, SettingScope
from radd.kernel import registries
from radd.exceptions import ConflictError

router = APIRouter(prefix="/mail/signatures", tags=["mailintake"])


@router.get("", response_model=SignatureSettings)
async def get_settings(session: Session, user: CurrentUser):
    await require_mail_admin(session, user)
    row = await session.get(MailSignatureSettings, 1)
    enabled = (
        await settings.resolve(session, SettingKey.AI_MAIL_SIGNATURE)
        if "ai" in registries.plugins
        else False
    )
    return SignatureSettings(rules=row.rules if row else [], ai_enabled=enabled)


@router.put("", response_model=SignatureSettings)
async def put_settings(data: SignatureSettings, session: Session, user: CurrentUser):
    await require_mail_admin(session, user)
    row = await session.scalar(
        select(MailSignatureSettings).where(MailSignatureSettings.id == 1).with_for_update()
    )
    if row is None:
        row = MailSignatureSettings(id=1)
        session.add(row)
    row.rules = [rule.model_dump() for rule in data.rules]
    if "ai" in registries.plugins:
        await settings.set_value(
            session,
            SettingKey.AI_MAIL_SIGNATURE,
            SettingScope.INSTANCE,
            None,
            data.ai_enabled,
            actor_id=user.id,
        )
    elif data.ai_enabled:
        raise ConflictError("mail", reason="Enable and configure the AI plugin first")
    await session.flush()
    return data


@router.post("/preview")
async def preview(data: SignaturePreview, session: Session, user: CurrentUser):
    await require_mail_admin(session, user)
    signature, method = await detect(
        session, data.body, data.sender, rules=data.settings.rules, use_ai=data.settings.ai_enabled
    )
    return {
        "body": data.body[: -len(signature)] if signature else data.body,
        "signature": signature,
        "method": method,
    }


@router.post("/{kind}/{entity_id}/restore", status_code=204)
async def restore(kind: str, entity_id: uuid.UUID, session: Session, user: CurrentUser):
    if kind == "item":
        from radd.modules.items import service

        await service.restore_email_signature(session, entity_id, user)
    elif kind == "comment":
        from radd.modules.comments import service

        await service.restore_email_signature(session, entity_id, user)
    else:
        raise ConflictError("mail", reason="Unsupported signature parent")
