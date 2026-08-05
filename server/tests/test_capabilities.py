"""Chokepoint-2 parity (spec 93): the /capabilities registry must reproduce the
provider flags the old inlined `/instance/status` computed. Each plugin's
`CapabilitySpec.check()` replicates the exact `bool(settings.*)` expression the
endpoint used to inline, so `instance_status` (now a registry consumer) is
byte-for-byte equivalent for any config. Pure: reads the registry + settings.
"""

from radd.config import settings
from radd.kernel import capabilities as kcaps


def _map():
    return kcaps.capability_map()


def test_all_expected_capabilities_registered():
    keys = set(_map())
    assert {
        "sso", "ldap", "ai", "storage", "mfa", "smtp", "workers",
        "gitlab", "forgejo", "google_chat", "alertmanager", "email_intake",
    } <= keys


def test_capability_checks_match_the_old_inline_logic():
    cm = _map()
    # `sso` moved to a DB snapshot in spec 110 — asserted below with the other
    # registry-backed capabilities, not against the (now seed-only) env vars.
    assert cm["ldap"]["enabled"] == bool(settings.ldap_url and settings.ldap_user_domain)
    assert cm["ldap"]["bind_account"] == bool(
        settings.ldap_url and settings.ldap_bind_dn and settings.ldap_bind_password
    )
    assert cm["smtp"]["enabled"] == bool(settings.smtp_host)
    assert cm["mfa"]["enabled"] is True
    assert cm["workers"]["enabled"] == settings.run_workers


async def test_storage_ai_sso_and_forgejo_capabilities_reflect_their_db_snapshots():
    """Specs 101/102/110/111 moved these off env: the sync capability checks read
    the process-local snapshots the startup hooks (and admin writes) refresh."""
    from radd.modules.ai import registry as ai_registry
    from radd.modules.attachments import hosts
    from radd.modules.forgejo import service as forgejo_service
    from radd.modules.sso import registry as sso_registry

    await hosts.seed_from_env()  # empty table in a fresh test DB -> seeds one host
    await ai_registry.seed_from_env()  # inert without RADD_AI_PROVIDER; refreshes
    await sso_registry.seed_from_env()  # inert without RADD_OIDC_ISSUER; refreshes
    await forgejo_service.seed_from_env()  # inert without the env secret; refreshes
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
    # Exactly the five the old instance_status hardcoded — now derived, so a new
    # connector plugin would appear here with no edit to projects.
    assert set(connectors) == {
        "gitlab", "forgejo", "google_chat", "alertmanager", "email_intake",
    }
    assert connectors["gitlab"] == bool(settings.gitlab_webhook_secret)
    # forgejo is row-backed since spec 111 — asserted in the snapshot test above.
    assert connectors["google_chat"] == bool(settings.googlechat_webhook_url)
    assert connectors["alertmanager"] == bool(settings.alertmanager_token)
    assert connectors["email_intake"] == bool(settings.mail_imap_host)


def test_evaluate_is_serializable_shape():
    for c in kcaps.evaluate():
        assert set(c) == {"key", "label", "category", "enabled", "detail"}
        assert isinstance(c["enabled"], bool)
