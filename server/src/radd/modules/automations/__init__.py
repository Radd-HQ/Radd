from fastapi import Request
from fastapi.responses import JSONResponse

from .types import CONSUMER_NAME, AutomationEvent
from radd.kernel import EntityLinkSpec, NavItemSpec
from radd.kernel import EventTypeSpec, RaddPlugin, PluginUiManifest
from radd.kernel import CrudResourceSpec, PermissionSpec

from . import dispatcher, scheduler
from .builtin_actions import ACTION_NODES
from .builtin_routers import ROUTER_NODES
from .trigger_kinds import TRIGGER_KINDS
from .verdicts import VERDICT_NODES
from .templates import TEMPLATES
from . import subscribers  # noqa: F401 — registers the spec-119 item.creating hook
from .intake import ValidationBlocked
from .intake_router import router as intake_router
from .intake_schemas import finding_read
from .router import router
from .validation import ValidationUnavailable


async def _validation_blocked_handler(
    request: Request, exc: ValidationBlocked
) -> JSONResponse:
    """Spec 119's third 422 shape: `findings` (something a person should fix,
    rendered against its control), not `errors` (a value the API refused)."""
    return JSONResponse(
        status_code=422,
        content={
            "detail": "item validation failed",
            "findings": [
                finding_read(finding).model_dump() for finding in exc.verdict.findings
            ],
            "mode": exc.verdict.mode.value,
            "blocking": exc.verdict.blocks,  # derived, the same fact as the 409 and the 200
        },
    )


async def _validation_unavailable_handler(
    request: Request, exc: ValidationUnavailable
) -> JSONResponse:
    """The checks BROKE (→ 503): nothing for the submitter to fix, and no `findings` key."""
    return JSONResponse(status_code=503, content={"detail": str(exc)})


plugin = RaddPlugin(
    name="automations",
    entity_links=(
        EntityLinkSpec('automation_rule', ('/settings/automations',)),
    ),
    ui=PluginUiManifest(nav=(NavItemSpec(key="automations", label="Automations", path="/settings/automations",
            section="settings", group="Server", icon="zap", order=90, requires=("automation.manage",)),)),
    # RADD-1322: the built-in nodes are registered exactly as a plugin's are.
    automation_nodes=(*ROUTER_NODES, *ACTION_NODES, *VERDICT_NODES),
    # RADD-1323: the button, the clock and the draft check, as registered kinds.
    trigger_kinds=TRIGGER_KINDS,
    automation_templates=TEMPLATES,
    # Not triggers — a rule that fires on rules being edited is the loop guard's nightmare.
    event_types=(
        EventTypeSpec(
            AutomationEvent.CREATED, "Automation created", "Admin",
            trigger=False, entity_type="automation_rule",
        ),
        EventTypeSpec(
            AutomationEvent.UPDATED, "Automation updated", "Admin",
            has_changes=True, trigger=False, entity_type="automation_rule",
        ),
        EventTypeSpec(
            AutomationEvent.DELETED, "Automation deleted", "Admin",
            trigger=False, entity_type="automation_rule",
        ),
        EventTypeSpec(
            AutomationEvent.SCHEDULED, "Automation scheduled run", "System",
            trigger=False, entity_type="automation", audited=False,
        ),
        # RADD-1266: audited, never a trigger.
        EventTypeSpec(
            AutomationEvent.RUN_FAILED, "Automation run failed", "Admin",
            trigger=False, entity_type="automation_rule",
        ),
    ),
    consumer_names=(CONSUMER_NAME,),
    consumer_descriptions=((CONSUMER_NAME, "Runs automation rules"),),
    permissions=(
        PermissionSpec(
            "automation.manage", "global", "Manage global automation rules that can read and change issues through the system actor."
        ),
        PermissionSpec(
            "automation.act_as",
            "global",
            "Build automations whose actions run as someone else. Without it an "
            "author's automations always act as the author, and the Act as field "
            "is not offered at all — an affordance that is refused on save is "
            "worse than one that is absent.",
        ),
    ),
    crud_resources=(
        CrudResourceSpec("automation", "global", "automation rules", "automation.manage"),
    ),
    description=(
        "Automations: rules that react to events or run on a schedule and change issues, notify people or call out."
    ),
    depends_on=("projects", "auth", "workflow", "labels", "cycles", "releases", "items", "comments", "teams", "events", "fields", "itemtypes",),
    # RADD-1387: no longer leave, mailintake or participants — away-skipping
    # reads the PERSON_AVAILABILITY socket, and send_email / add_participant
    # are nodes those plugins contribute themselves.
    weak_depends=("notify", "forms"),
    routers=(router, intake_router),
    exception_handlers=(
        (ValidationBlocked, _validation_blocked_handler),
        (ValidationUnavailable, _validation_unavailable_handler),
    ),
    on_startup=(dispatcher.start, scheduler.start),
    on_shutdown=(dispatcher.stop, scheduler.stop),
)
