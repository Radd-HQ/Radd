"""LDAP bind core (spec 42) — the pure pieces the directory login hangs on:
base-DN derivation, the username shape gate, filter construction (injection
safety), and entry→DirectoryUser mapping with its documented fallbacks. The
wire bind itself is the production pipe-status pattern, checked against a real
directory at deploy time; the provision/session path is exercised in-process
via ASGI with a stubbed lookup (see the spec's Verification section).
"""

from radd.config import settings
from radd.modules.ldap.service import (
    base_dn,
    directory_user_from_entry,
    group_search_filter,
    transitive_member_filter,
)
from radd.modules.ldap.types import LDAP_MATCHING_RULE_IN_CHAIN, USERNAME_RE


def _overlay(monkeypatch, **kw):
    """RADD-846: the sync helpers read the resolved CONNECTION overlay, not
    raw env — tests set the overlay the way a cascade refresh would."""
    from radd.modules.ldap import service

    base = dict(url="", user_domain="", bind_dn="", bind_password="", admin_groups="")
    base.update(kw)
    monkeypatch.setattr(service, "_conn", service.LdapConn(**base))


def test_base_dn_derived_from_upn_domain(monkeypatch):
    _overlay(monkeypatch, user_domain="ad.example.com")
    monkeypatch.setattr(settings, "ldap_base_dn", "")
    assert base_dn() == "DC=ad,DC=example,DC=com"


def test_base_dn_explicit_override_wins(monkeypatch):
    monkeypatch.setattr(settings, "ldap_user_domain", "ad.example.com")
    monkeypatch.setattr(settings, "ldap_base_dn", "OU=people,DC=example,DC=com")
    assert base_dn() == "OU=people,DC=example,DC=com"


def test_username_shape_gate():
    assert USERNAME_RE.match("j.doe-01_x")
    assert not USERNAME_RE.match("")
    assert not USERNAME_RE.match("a" * 65)
    # DN / filter syntax never reaches the wire
    for hostile in ("j doe", "*", "admin)(cn=*", "cn=x,dc=y", "user@dom"):
        assert not USERNAME_RE.match(hostile), hostile


def test_filters_escape_hostile_values():
    group = group_search_filter("td-(admins)*")
    assert "(admins)" not in group  # parens escaped
    assert group == r"(&(objectClass=group)(cn=td-\28admins\29\2a))"
    member = transitive_member_filter("jdoe", "CN=g(1),DC=x")
    assert LDAP_MATCHING_RULE_IN_CHAIN in member
    assert member.startswith("(&(sAMAccountName=jdoe)")
    assert r"\28" in member and "g(1)" not in member


def test_entry_mapping_prefers_directory_attributes(monkeypatch):
    monkeypatch.setattr(settings, "ldap_user_domain", "ad.example.com")
    # ldap3 returns attribute values as lists
    user = directory_user_from_entry(
        "jdoe", {"mail": ["J.Doe@Example.com"], "displayName": ["Jane Doe"]}, is_admin=True
    )
    assert user.email == "j.doe@example.com"  # lowered, like local auth
    assert user.name == "Jane Doe"
    assert user.is_admin


def test_entry_mapping_fallbacks_upn_and_username(monkeypatch):
    _overlay(monkeypatch, user_domain="ad.example.com")
    user = directory_user_from_entry("jdoe", {}, is_admin=False)
    assert user.email == "jdoe@ad.example.com"  # UPN when the mail attribute is absent
    assert user.name == "jdoe"
    assert not user.is_admin


def test_bind_account_enabled_gate(monkeypatch):
    from radd.modules.ldap.service import bind_account_enabled

    _overlay(monkeypatch, url="ldaps://ad.example.com:636")
    assert not bind_account_enabled()
    _overlay(
        monkeypatch,
        url="ldaps://ad.example.com:636",
        bind_dn="CN=svc,DC=ad,DC=example,DC=com",
        bind_password="secret",
        user_domain="ad.example.com",
    )
    assert bind_account_enabled()


def test_directory_entry_mapping_skips_emailless(monkeypatch):
    from radd.modules.ldap.service import _entry_to_directory_user

    monkeypatch.setattr(settings, "ldap_user_domain", "ad.example.com")
    monkeypatch.setattr(settings, "ldap_email_attribute", "mail")
    monkeypatch.setattr(settings, "ldap_name_attribute", "displayName")
    ok = _entry_to_directory_user(
        {"sAMAccountName": ["jdoe"], "mail": ["J.Doe@Example.com"], "displayName": ["Jane Doe"]}
    )
    assert ok.email == "j.doe@example.com" and ok.name == "Jane Doe" and ok.is_admin is False
    # no mail attribute -> skipped (don't invent UPNs for bulk import)
    assert _entry_to_directory_user({"sAMAccountName": ["svc"], "displayName": ["Svc"]}) is None
    # no sAMAccountName -> skipped
    assert _entry_to_directory_user({"mail": ["x@example.com"]}) is None


def test_entry_mapping_honors_configured_attributes(monkeypatch):
    monkeypatch.setattr(settings, "ldap_user_domain", "ad.example.com")
    monkeypatch.setattr(settings, "ldap_email_attribute", "userPrincipalName")
    monkeypatch.setattr(settings, "ldap_name_attribute", "cn")
    user = directory_user_from_entry(
        "jdoe", {"userPrincipalName": ["jdoe@corp.example.com"], "cn": ["jdoe cn"]}, False
    )
    assert user.email == "jdoe@corp.example.com"
    assert user.name == "jdoe cn"


async def test_connection_resolves_through_the_cascade():
    """RADD-846: a Directory-page write beats env at the next boundary, and
    what the DB does not override keeps coming from env — no restart either way."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from radd.config import settings as config
    from radd.modules.ldap import service
    from radd.modules.settings import service as settings_service
    from radd.modules.settings.types import SettingKey, SettingScope

    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await settings_service.set_value(
            session, SettingKey.LDAP_URL, SettingScope.INSTANCE, None, "ldaps://db.example.com:636"
        )
        conn = await service.refresh_conn(session)
        assert conn.url == "ldaps://db.example.com:636"
        assert conn.user_domain == config.ldap_user_domain
        await session.rollback()
    await engine.dispose()
    # the rollback discarded the write the overlay was refreshed with — reseed
    service._conn = service._env_conn()
