"""TOTP core (spec 48) — RFC 6238 vectors (SHA-1 profile, truncated to the
6-digit app convention) + drift window + the provisioning URI contract."""

import base64

from radd.modules.auth.totp import code_at, generate_secret, provisioning_uri, verify_code

# RFC 6238 Appendix B secret ("12345678901234567890") — 8-digit vectors
# 94287082 / 07081804 / 14050471 truncate to these 6-digit codes.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()
RFC_VECTORS = [(59, "287082"), (1111111109, "081804"), (1111111111, "050471")]


def test_rfc6238_vectors():
    for timestamp, expected in RFC_VECTORS:
        assert code_at(RFC_SECRET, timestamp) == expected


def test_verify_accepts_one_step_drift_only():
    t = 1111111109  # step boundary at 1111111110
    code = code_at(RFC_SECRET, t)
    assert verify_code(RFC_SECRET, code, t)
    assert verify_code(RFC_SECRET, code, t + 30)  # one step late: accepted
    assert not verify_code(RFC_SECRET, code, t + 90)  # three steps: rejected
    assert not verify_code(RFC_SECRET, "000000", t) or code == "000000"


def test_verify_tolerates_spaces_and_is_exact():
    t = 59
    assert verify_code(RFC_SECRET, " 287 082 ".replace(" ", " "), t)
    assert not verify_code(RFC_SECRET, "287083", t)


def test_generate_secret_is_base32_160bit():
    secret = generate_secret()
    assert len(base64.b32decode(secret)) == 20
    assert secret != generate_secret()


def test_provisioning_uri_contract():
    uri = provisioning_uri("ABC234", "user@example.com")
    assert uri.startswith("otpauth://totp/Radd%3Auser%40example.com?")
    assert "secret=ABC234" in uri and "issuer=Radd" in uri
    assert "digits=6" in uri and "period=30" in uri and "algorithm=SHA1" in uri
