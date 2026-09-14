"""Project teardown, this module's share (RADD-1174).

`projects` dispatches two in-transaction hooks and owns nothing here: INSPECTING
asks what of ours dies with the project (the confirmation dialog's numbers, and
the count the `project.deleted` event records), DELETING removes what the
database cannot cascade on its own. Registered at import, like the
`project.created` seeding hooks.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.modules.projects.types import Blocker, ProjectHook, ProjectInspection

from .models import MailRule, MailSource

MAIL_SETTINGS_HINT = "Settings → Email"


@hooks.on(ProjectHook.INSPECTING)
async def block_while_mail_routes_here(session: AsyncSession, inspection: ProjectInspection) -> None:
    """Refuse, never degrade. `default_project_id` is `SET NULL`, and a source
    with no default makes `intake.accept` raise on every message — the webhook
    turns that into a 5xx that bounces valid mail. A rule's project is
    `CASCADE`, which would silently reroute its matches to the default. Both
    are one repoint away for the admin, and the blocker names which."""
    project_id = inspection.project.id
    sources = (
        await session.execute(select(MailSource).where(MailSource.default_project_id == project_id))
    ).scalars()
    for source in sources:
        inspection.blockers.append(
            Blocker(
                kind="mail_source",
                id=str(source.id),
                label=f"mail source “{source.name}” ({source.address}) lands here by default",
                hint=MAIL_SETTINGS_HINT,
            )
        )
    rules = (
        await session.execute(
            select(MailRule, MailSource.name)
            .join(MailSource, MailSource.id == MailRule.source_id)
            .where(MailRule.project_id == project_id)
        )
    ).all()
    for rule, source_name in rules:
        inspection.blockers.append(
            Blocker(
                kind="mail_rule",
                id=str(rule.id),
                label=f"mail rule “{rule.name}” on “{source_name}” routes here",
                hint=MAIL_SETTINGS_HINT,
            )
        )
