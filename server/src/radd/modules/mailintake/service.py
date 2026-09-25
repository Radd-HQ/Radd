"""Public seam for mail contacts and the item-mail transport.

Other modules (forms' public submits, the csat sender's recipient resolution
[spec 65]; automations in spec 66) address external requesters exclusively
through these functions — the `mail_contacts` table stays private to this module.

`send_item_mail` / `send_plain_mail` / `outbound_configured` / `mail_health` are
re-exported from `transport.py` (RADD-968, widened by RADD-983/1036): they are
the seam NOTIFY, CSAT and the automation `send_email` action call to put a
message on the wire, and a caller looks for a module's public functions here,
not in a file named after the implementation. Since RADD-983 there is no mail
leaving the INSTANCE by any other route. (The acknowledgment that used to live
here is an automation template since RADD-1318.)
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.models import User
from radd.modules.auth.types import UserSource
from radd.modules.automations.types import SYSTEM_ACTOR_ID

from .models import MailContact
from .transport import (
    MailFailure,
    MailHealth,
    mail_health,
    outbound_configured,
    send_item_mail,
    send_plain_mail,
)
from .types import SentMailKind

__all__ = [
    "MailFailure",
    "MailHealth",
    "contact_for_item",
    "contacts_for_item",
    "mail_health",
    "mailable_user",
    "outbound_configured",
    "send_item_mail",
    "send_plain_mail",
    "SentMailKind",
    "upsert_contact",
]


def mailable_user(user: User | None) -> bool:
    """Is there a PERSON's mailbox behind this account? (RADD-996, RADD-983)

    Four kinds of account are not a person to mail: inactive, address-less, a
    spec-113 SERVICE account (`radd-agent@service.radd.local` does not receive
    — the column requires an address, nobody reads it), and the system actor
    (`automation@radd.system`, the identity mail intake and every engine write
    carry). The live evidence is that service accounts had been getting
    notification mail since v0.29.0 and the relay was rate-limited for
    repeatedly posting to addresses that bounce.

    It lives on the MAIL module because the answer is about mailability, and
    because CSAT and the `send_email` automation action are the two callers
    that had no such check at all — both resolve a user-shaped role (the
    reporter, the assignee) and both mailed whatever came back. Notify carries
    its own copy of the same rule for one structural reason: notify loads
    BEFORE mailintake and reaches it only deferred and feature-detected, so it
    cannot import this at module scope. The predicate is small and stated
    identically in both places; if a third caller appears it belongs in `auth`.

    A property of the ACCOUNT, not of the attempt — so a caller treats a False
    the way it treats a permanent refusal (drop it, never retry), where a
    delivery failure is the retrying case.
    """
    if user is None or not user.active or not user.email:
        return False
    if user.id == SYSTEM_ACTOR_ID:
        return False
    return user.source not in (UserSource.SERVICE.value, UserSource.PRINCIPAL.value)

#: Primary first, then oldest, then alphabetical. Used by both reads, so "the
#: primary" and "the first of all of them" can never disagree — the standing
#: risk of keeping a singular seam beside a plural one.
#:
#: The address is the last tiebreak rather than the id because `created_at` is
#: `func.now()`, and Postgres' `now()` is TRANSACTION time: every contact
#: captured from ONE message carries an identical timestamp, so "which came
#: first" has no answer among them and a uuid4 tiebreak would shuffle the rail
#: on every read. (The same trap `forms.requests._comment_signals` documents.)
_CONTACT_ORDER = (MailContact.is_primary.desc(), MailContact.created_at, MailContact.email)


async def contact_for_item(session: AsyncSession, item_id: uuid.UUID) -> MailContact | None:
    """The item's PRIMARY contact — its requester, or None.

    Unchanged in meaning for every existing caller (CSAT's recipient, the
    send_email `contact` role, the singular endpoint) even though the table is
    now n-ary (RADD-980): each of those addresses ONE person, and the person
    they mean is whoever raised the ticket.

    **Filtered on `is_primary`, not merely ordered by it.** An item whose only
    external addresses were COPIED IN has no requester here — it was raised by
    a real user, and its reporter is who those seams should fall back to.
    Answering with the oldest row instead would send a satisfaction survey to a
    bystander about a ticket they never opened.
    """
    return await session.scalar(
        select(MailContact)
        .where(MailContact.item_id == item_id, MailContact.is_primary.is_(True))
        .order_by(*_CONTACT_ORDER)
    )


async def contacts_for_item(
    session: AsyncSession, item_id: uuid.UUID
) -> list[MailContact]:
    """Everyone external on this item's mail thread, primary first (RADD-980).

    This is what an OUTBOUND reply fans out over: the requester CC'd their
    colleague, and answering only the person whose address happened to be in
    `From:` is how two of the three people who asked never hear back.
    """
    rows = await session.execute(
        select(MailContact).where(MailContact.item_id == item_id).order_by(*_CONTACT_ORDER)
    )
    return list(rows.scalars())


async def upsert_contact(
    session: AsyncSession,
    item_id: uuid.UUID,
    *,
    email: str,
    name: str = "",
    message_id: str | None = None,
    copied_in: bool = False,
) -> MailContact:
    """Record one external address on an item, or refresh what is known about it.

    Keyed on `(item_id, email)` since RADD-980, so a CC copied on every message
    refreshes ONE row rather than accumulating one per message. `message_id`
    advances that contact's own last-said marker and nobody else's.

    **The first person who WROTE becomes the primary; somebody merely copied in
    never does.** `copied_in` is the only lever, and it can only withhold the
    badge — it cannot award it, and nothing demotes an existing primary. A flag
    that could promote is a flag some caller eventually passes for a CC, and
    then a ticket's requester silently changes on message four.

    That asymmetry is what makes the fallbacks land right. An issue an agent
    raised in the UI, that a customer later emails into, gains its requester the
    moment they write. An issue a colleague raised BY EMAIL, with a customer
    copied in, gains no primary at all — so CSAT and the send_email `contact`
    role fall through to the reporter, who is that colleague.
    """
    address = email.strip().lower()
    existing = await contacts_for_item(session, item_id)
    contact = next((row for row in existing if row.email == address), None)
    if contact is None:
        contact = MailContact(
            item_id=item_id,
            email=address,
            name=name,
            last_message_id=message_id or None,
            is_primary=not copied_in and not any(row.is_primary for row in existing),
        )
        session.add(contact)
    else:
        if message_id:
            contact.last_message_id = message_id
        if name and not contact.name:
            contact.name = name
    await session.flush()
    return contact
