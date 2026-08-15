"""RADD-677 — TOTP recovery codes: the self-service path out of a lost phone.

Real flows through the service seam: enroll, confirm (codes minted in the
same breath), sign in with a burned code exactly once, regenerate, disable.
"""

import time
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import UnauthorizedError
from radd.modules.auth import service as auth_service, totp
from radd.modules.auth.models import TotpRecoveryCode, User
from radd.modules.auth.schemas import UserCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


PASSWORD = "recovery-pass-1"


async def _enrolled_user(db) -> tuple[User, str, list[str]]:
    """A user with confirmed TOTP: returns (user, totp_secret, recovery_codes)."""
    user = await auth_service.create_user(
        db,
        UserCreate(
            email=f"rc-{uuid.uuid4().hex[:8]}@example.com",
            name="Recovery Probe",
            password=PASSWORD,
        ),
    )
    row = await auth_service.totp_setup(db, user)
    codes = await auth_service.totp_confirm(
        db, user, totp.code_at(row.secret, int(time.time()))
    )
    return user, row.secret, codes


def test_code_shapes():
    codes = totp.generate_recovery_codes()
    assert len(codes) == totp.RECOVERY_CODE_COUNT
    assert len(set(codes)) == len(codes)
    for code in codes:
        assert totp.looks_like_recovery_code(code)
    assert not totp.looks_like_recovery_code("123456")  # a TOTP code is not one
    # normalization forgives what humans type from a printout
    assert totp.hash_recovery_code(" AbCde-Fgh23 ") == totp.hash_recovery_code("abcdefgh23")


async def test_confirm_mints_codes_and_status_counts_them(db):
    user, _secret, codes = await _enrolled_user(db)
    assert len(codes) == totp.RECOVERY_CODE_COUNT
    assert await auth_service.recovery_codes_remaining(db, user.id) == len(codes)
    stored = (
        (await db.execute(select(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user.id)))
        .scalars()
        .all()
    )
    assert all(len(row.code_hash) == 64 for row in stored)  # hashes, never plaintext
    assert not any(code in {row.code_hash for row in stored} for code in codes)


async def test_a_recovery_code_signs_in_exactly_once(db):
    user, _secret, codes = await _enrolled_user(db)
    burned = codes[0]
    got = await auth_service.authenticate_with_totp(db, user.email, PASSWORD, burned)
    assert got.id == user.id
    assert await auth_service.recovery_codes_remaining(db, user.id) == len(codes) - 1
    with pytest.raises(UnauthorizedError):
        await auth_service.authenticate_with_totp(db, user.email, PASSWORD, burned)
    # the TOTP code itself still works after a recovery sign-in
    row = await auth_service.totp_row(db, user.id)
    again = await auth_service.authenticate_with_totp(
        db, user.email, PASSWORD, totp.code_at(row.secret, int(time.time()))
    )
    assert again.id == user.id


async def test_regenerate_invalidates_the_old_batch(db):
    user, secret, old_codes = await _enrolled_user(db)
    new_codes = await auth_service.regenerate_recovery_codes(
        db, user, totp.code_at(secret, int(time.time()))
    )
    assert set(new_codes).isdisjoint(old_codes)
    assert await auth_service.recovery_codes_remaining(db, user.id) == len(new_codes)
    with pytest.raises(UnauthorizedError):
        await auth_service.authenticate_with_totp(db, user.email, PASSWORD, old_codes[1])


async def test_regenerate_requires_a_live_code(db):
    user, _secret, _codes = await _enrolled_user(db)
    with pytest.raises(UnauthorizedError):
        await auth_service.regenerate_recovery_codes(db, user, "000000")


async def test_disable_accepts_a_recovery_code_and_clears_the_batch(db):
    """Losing the phone is exactly when disabling-to-re-enroll is legitimate."""
    user, _secret, codes = await _enrolled_user(db)
    await auth_service.totp_disable(db, user, codes[0])
    assert await auth_service.totp_row(db, user.id) is None
    assert await auth_service.recovery_codes_remaining(db, user.id) == 0
