"""/capabilities is built from each plugin's `CapabilitySpec`; these pin the
registered set and what each check reads.
"""

from radd.config import settings
from radd.kernel import capabilities as kcaps
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole


def _map():
    return kcaps.capability_map()


def _admin() -> User:
    """An instance admin the route can be called with directly — in memory, no session.
    `active` is set because an unflushed row has none, and the bypass reads it."""
    return User(email="caps-admin@example.com", name="Caps Admin", instance_role=InstanceRole.ADMIN.value, active=True)


def test_all_expected_capabilities_registered():
    keys = set(_map())
    assert {
        "sso", "ldap", "ai", "storage", "outbound_mail", "workers",
        "gitlab", "forgejo", "alertmanager", "email_intake",
    } <= keys


def test_capability_checks_match_the_old_inline_logic():
    cm = _map()
    # `sso` reads a DB snapshot: asserted below with the other registry-backed ones.
    assert cm["ldap"]["enabled"] == bool(settings.ldap_url and settings.ldap_user_domain)
    assert cm["ldap"]["bind_account"] == bool(
        settings.ldap_url and settings.ldap_bind_dn and settings.ldap_bind_password
    )
    assert "smtp" not in cm  # outbound mail is read from sender ROWS (below)
    assert "mfa" not in cm  # the policy is the `require_mfa` setting
    assert cm["workers"]["enabled"] == settings.run_workers


async def test_storage_ai_sso_and_forgejo_capabilities_reflect_their_db_snapshots():
    """Specs 101/102/110/111 moved these off env: the sync capability checks read
    the process-local snapshots the startup hooks (and admin writes) refresh."""
    from radd.modules.ai import registry as ai_registry
    from radd.modules.attachments import hosts
    from radd.modules.forgejo.service import store as forgejo_service
    from radd.modules.gitlab.service import store as gitlab_service
    from radd.modules.sso import registry as sso_registry

    await hosts.seed_from_env()  # empty table in a fresh test DB -> seeds one host
    await ai_registry.seed_from_env()  # inert without RADD_AI_PROVIDER; refreshes
    await sso_registry.seed_from_env()  # inert without RADD_OIDC_ISSUER; refreshes
    await forgejo_service.seed_from_env()  # inert without the env secret; refreshes
    await gitlab_service.seed_from_env()  # RADD-1253: same rule
    cm = _map()
    default = hosts.default_snapshot()
    assert cm["storage"]["enabled"] == bool(default)
    assert cm["storage"]["backend"] == default.get("type", "")
    chat = ai_registry.role_snapshot().get("chat")
    assert cm["ai"]["enabled"] == (chat is not None)
    assert cm["ai"]["provider"] == (chat or {}).get("provider", "")
    assert cm["sso"]["enabled"] == bool(sso_registry.snapshot())
    assert cm["sso"]["providers"] == len(sso_registry.snapshot())
    # Spec 111 made connections rows (env secret SEED-ONLY): the pill counts
    # ACTIVE rows, so a UI-created connection lights it with no env at all.
    assert cm["forgejo"]["enabled"] == (forgejo_service.active_connection_count() > 0)


def test_connectors_derive_generically_from_the_connector_category():
    cm = _map()
    connectors = {k: v["enabled"] for k, v in cm.items() if v.get("category") == "connector"}
    # The five the old instance_status hardcoded plus github (RADD-1129) — now
    # derived, so a new connector plugin appears here with no edit to projects.
    assert set(connectors) == {
        "gitlab", "forgejo", "github", "alertmanager", "email_intake",
    }
    # gitlab is row-backed since RADD-1253, like forgejo (asserted in the snapshot test above).
    from radd.modules.gitlab.service import store as gitlab_service

    assert connectors["gitlab"] == (gitlab_service.active_connection_count() > 0)
    # alertmanager is row-backed since RADD-1317 (receivers).
    from radd.modules.alertmanager import service as alertmanager_service

    assert connectors["alertmanager"] == (alertmanager_service.active_receiver_count() > 0)
    # email_intake is row-backed since RADD-958 — asserted against rows below.


async def test_email_intake_capability_follows_the_enabled_source_rows():
    """RADD-975. The capability reads the snapshot `mailintake.registry`
    refreshes from ENABLED MailSource/MailSender rows; the old assertion compared
    it to `settings.mail_imap_host`, which both sides ignored, so it held
    whatever the registry did. Now: no enabled rows → off; an enabled polled
    source → on; the same row disabled → off."""
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from radd.modules.mailintake import registry
    from radd.modules.mailintake.models import MailSender, MailSource
    from radd.modules.mailintake.types import MailSenderKind, MailSourceKind

    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        # Inside this rolled-back transaction, nothing else is enabled.
        await db.execute(update(MailSource).values(enabled=False))
        await db.execute(update(MailSender).values(enabled=False))
        await registry.refresh_snapshot(db)
        assert _map()["email_intake"]["enabled"] is False

        source = await registry.save_source(
            db, MailSource(name="Inbox", kind=MailSourceKind.IMAP.value, host="imap.example.com", username="u")
        )
        assert _map()["email_intake"]["enabled"] is True

        source.enabled = False
        await registry.save_source(db, source)
        assert _map()["email_intake"]["enabled"] is False

        # RADD-1389: Outbound email follows the SENDER rows, not RADD_SMTP_HOST —
        # the env only seeds a row, so an env check read Off on a working instance.
        assert _map()["outbound_mail"]["enabled"] is False
        sender = await registry.save_sender(
            db, MailSender(name="Desk", kind=MailSenderKind.SMTP.value, host="smtp.example.com", from_address="desk@example.com")
        )
        assert _map()["outbound_mail"]["enabled"] is True
        sender.enabled = False
        await registry.save_sender(db, sender)
        assert _map()["outbound_mail"]["enabled"] is False
        await db.rollback()
    await engine.dispose()


def test_evaluate_is_serializable_shape():
    for c in kcaps.evaluate():
        assert set(c) == {"key", "label", "category", "enabled", "detail"}
        assert isinstance(c["enabled"], bool)


async def test_navigation_carries_ownership_and_generic_display_constraints(monkeypatch):
    from radd.kernel import NavItemSpec, PluginUiManifest, RaddPlugin, registries
    from radd.modules.capabilities.router import get_capabilities

    nav = NavItemSpec(
        key="fixture", label="Fixture", path="/settings/fixture", section="settings",
        group="Server", requires_admin=True,
    )
    plugin = RaddPlugin(name="fixture", ui=PluginUiManifest(nav=(nav,)))
    monkeypatch.setattr(registries, "plugins", {"fixture": plugin})
    monkeypatch.setattr(registries, "nav", [nav])
    manifest = await get_capabilities(_admin())
    assert manifest.nav[0].plugin == "fixture"
    assert manifest.nav[0].group == "Server"
    assert manifest.nav[0].requires_admin is True
    monkeypatch.setattr(registries, "plugins", {})
    monkeypatch.setattr(registries, "nav", [])
    assert (await get_capabilities(_admin())).nav == []


async def test_each_capability_names_its_owner():
    """RADD-1389: Server status links a row through its OWNER plugin, so the row
    says who declared it — and outbound email is mailintake's, not the aggregator's."""
    from radd.modules.capabilities.router import get_capabilities

    owners = {c.key: c.plugin for c in (await get_capabilities(_admin())).capabilities}
    assert owners["outbound_mail"] == "mailintake"
    assert owners["workers"] == "capabilities"
    assert owners["ldap"] == "ldap"
    assert all(owners.values()), "every loaded capability has a loaded owner"


async def test_capability_detail_travels_to_instance_admins_only(db):
    """RADD-1459: `/capabilities` answers every actor — a member, a public-project
    visitor — so the on/off flags, the plugin set, the nav and the remotes reach all of
    them; what a plugin's check() reports beyond that (the AI provider's name, whether a
    bind account exists, the `summary` line) is operational status for the Server status
    page and the plugin admin pages, and reaches instance admins alone."""
    from _factories import make_user
    from radd.modules.auth import principals
    from radd.modules.auth.deps import anyone_user
    from radd.modules.capabilities.router import get_capabilities

    await principals.ensure_builtin_accounts(db)
    member = await make_user(db)
    admin = await make_user(db, role=InstanceRole.ADMIN)
    admin_view = {c.key: c for c in (await get_capabilities(admin)).capabilities}
    assert {"bind_account", "summary"} <= set(admin_view["ldap"].detail)
    assert "summary" in admin_view["sso"].detail and "provider" in admin_view["ai"].detail
    for actor in (member, await anyone_user(db)):
        manifest = await get_capabilities(actor)
        assert manifest.plugins and manifest.nav is not None
        assert all(c.detail == {} for c in manifest.capabilities), "no operational detail"
        # The same rows, the same flags — only the detail is withheld.
        assert {c.key: (c.enabled, c.plugin) for c in manifest.capabilities} == {
            key: (c.enabled, c.plugin) for key, c in admin_view.items()
        }
