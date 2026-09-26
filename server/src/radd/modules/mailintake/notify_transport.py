"""This plugin as notify's MAIL_TRANSPORT provider (RADD-1385), registered on the
manifest so disabling the plugin withdraws it. An adapter over `transport`: sender
rows (env relay as fallback), threading on the item, `mail.sent`/`mail.failed`."""

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.notify.transport import NotificationMail

from . import transport


class NotificationMailTransport:
    """`MailTransport` for notify's per-event mail and digest."""

    async def configured(self, session: AsyncSession) -> bool:
        return await transport.outbound_configured(session)

    async def send(self, session: AsyncSession, mail: NotificationMail) -> bool:
        """One notification email: threaded on its issue, else itemless plain mail.
        The caller's session, so `mail.sent` commits with the row it describes."""
        if mail.item_id is not None:
            sent = await transport.send_item_mail(
                session,
                item_id=mail.item_id,
                to_address=mail.to_address,
                to_name=mail.to_name,
                subject=mail.subject,
                text=mail.text,
                html=mail.html,
                comment_id=mail.comment_id,
                failure=mail.failure,
                headers=mail.headers,
                kind=mail.kind,
            )
        else:
            sent = await transport.send_plain_mail(
                session,
                to_address=mail.to_address,
                to_name=mail.to_name,
                subject=mail.subject,
                text=mail.text,
                html=mail.html,
                failure=mail.failure,
                headers=mail.headers,
                kind=mail.kind,
            )
        return bool(sent)
