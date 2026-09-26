"""This plugin as notify's mail transport (RADD-1385).

The kernel `MAIL_TRANSPORT` socket's provider. `notify` used to import
`mailintake.service` behind a `try: import` that could never fail — plugin code
is always importable — so notification email kept flowing through a mail plugin
the plugin manager had switched off. Registered on the manifest instead: disable
this plugin and notify records its email rows as undeliverable, and the inbox
carries on.

An adapter, like `approvals/gate.py`: the two questions notify asks, answered by
the transport functions every other sender here already uses — sender rows (the
env relay as their fallback), threading on the item, `mail.sent`/`mail.failed`.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.notify.transport import NotificationMail

from . import transport


class NotificationMailTransport:
    """`MailTransport` for notify's per-event mail and digest."""

    async def configured(self, session: AsyncSession) -> bool:
        return await transport.outbound_configured(session)

    async def send(self, session: AsyncSession, mail: NotificationMail) -> bool:
        """One notification email. About one issue, it threads on that issue
        (a Reply lands back on it); otherwise — a digest, a page — it goes as
        itemless plain mail. The caller's session: the `mail.sent` event belongs
        in the transaction that stamps the row it describes."""
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
