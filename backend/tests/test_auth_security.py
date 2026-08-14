"""The auth primitives, tested without a database.

Everything in `app/core/security.py` is pure, which is the whole reason it is
pure: the rules that decide whether a password is accepted, whether a code
matches and whether a token can be trusted are the ones most worth pinning
down, and none of them should need Postgres to check.

The database-backed halves -- OTP issue/redeem against `email_otps`, and the
route behaviour -- are exercised by `scripts/check_auth_flow.py`, which needs a
live server.
"""

import time
import uuid

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    MAX_PASSWORD_BYTES,
    TokenError,
    create_access_token,
    decode_access_token,
    generate_otp,
    hash_otp,
    hash_password,
    normalize_email,
    normalize_username,
    password_problem,
    username_problem,
    verify_otp,
    verify_password,
)

GOOD_PASSWORD = "Sup3rSecret"


# ── passwords ─────────────────────────────────────────────────────────────


def test_password_round_trips():
    digest = hash_password(GOOD_PASSWORD)
    assert digest != GOOD_PASSWORD
    assert verify_password(GOOD_PASSWORD, digest)
    assert not verify_password(GOOD_PASSWORD + "x", digest)


def test_password_hash_is_salted():
    """Two hashes of one password must differ, or the table leaks which users
    share a password the moment anyone reads it."""
    assert hash_password(GOOD_PASSWORD) != hash_password(GOOD_PASSWORD)


def test_verify_password_survives_a_corrupt_hash():
    """A malformed row is a failed login, not a 500.

    bcrypt raises `ValueError` on a hash it cannot parse; letting that escape
    would turn one bad row into an unhandled error on every attempt against it.
    """
    assert not verify_password(GOOD_PASSWORD, "not-a-bcrypt-hash")
    assert not verify_password(GOOD_PASSWORD, "")


@pytest.mark.parametrize(
    "password,expect_problem",
    [
        (GOOD_PASSWORD, False),
        ("Sh0rt", True),  # under 8
        ("alllowercase1", True),  # no upper
        ("ALLUPPERCASE1", True),  # no lower
        ("NoDigitsHere", True),  # no digit
    ],
)
def test_password_policy(password, expect_problem):
    assert (password_problem(password) is not None) is expect_problem


def test_password_over_bcrypt_limit_is_refused_not_truncated():
    """bcrypt silently ignores everything past 72 bytes.

    Accepting a 200-character passphrase would advertise strength the hash does
    not have, so the policy refuses it with a message rather than storing a
    hash of its first 72 bytes.
    """
    too_long = "Aa1" + "x" * MAX_PASSWORD_BYTES
    assert password_problem(too_long) is not None


# ── identifiers ───────────────────────────────────────────────────────────


def test_email_normalisation_is_what_makes_the_unique_index_work():
    assert normalize_email("  Riya.Mehta@YMSLI.com ") == "riya.mehta@ymsli.com"
    assert normalize_username("  Riya.Mehta ") == "riya.mehta"


@pytest.mark.parametrize(
    "username,ok",
    [
        ("riya.mehta", True),
        ("riya_mehta-1", True),
        ("ab", False),  # too short
        ("has spaces", False),
        ("has@symbol", False),
        ("x" * 65, False),  # too long
    ],
)
def test_username_policy(username, ok):
    assert (username_problem(username) is None) is ok


# ── one-time codes ────────────────────────────────────────────────────────


def test_otp_is_six_digits_and_keeps_leading_zeros():
    """Zero-padding is what keeps all million values reachable -- stripping it
    would quietly shrink the space every time the draw started with a zero."""
    for _ in range(200):
        code = generate_otp()
        assert len(code) == 6
        assert code.isdigit()


def test_otp_verify_matches_only_the_right_code():
    code = generate_otp()
    digest = hash_otp(code)
    assert verify_otp(code, digest)
    assert not verify_otp("000000" if code != "000000" else "111111", digest)


def test_otp_hash_is_not_the_code():
    code = "042917"
    assert code not in hash_otp(code)
    assert len(hash_otp(code)) == 64


# ── access tokens ─────────────────────────────────────────────────────────


def test_token_round_trips_with_the_claims_the_api_authorises_on():
    user_id = uuid.uuid4()
    claims = decode_access_token(create_access_token(user_id, "admin", "riya@ymsli.com"))
    assert claims["sub"] == str(user_id)
    assert claims["role"] == "admin"
    assert claims["email"] == "riya@ymsli.com"


def test_token_signed_with_another_key_is_refused():
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "role": "admin", "exp": int(time.time()) + 3600},
        "not-the-servers-secret",
        algorithm="HS256",
    )
    with pytest.raises(TokenError):
        decode_access_token(forged)


def test_unsigned_token_is_refused():
    """`alg: none` is the classic JWT forgery. `decode_access_token` pins the
    algorithm list, so a token that declares its own is never honoured."""
    forged = jwt.encode({"sub": str(uuid.uuid4()), "role": "admin"}, None, algorithm="none")
    with pytest.raises(TokenError):
        decode_access_token(forged)


def test_expired_token_is_refused():
    expired = jwt.encode(
        {"sub": str(uuid.uuid4()), "role": "admin", "exp": int(time.time()) - 10},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(TokenError):
        decode_access_token(expired)


def test_garbage_is_refused_rather_than_raising_something_unhandled():
    for value in ("", "not.a.token", "a.b.c"):
        with pytest.raises(TokenError):
            decode_access_token(value)


# ── configuration guards ──────────────────────────────────────────────────


def test_otp_is_not_echoed_when_email_is_configured():
    """Three conditions guard the debug echo, and each has failed somewhere.

    Checked by construction rather than by mutating the live settings object,
    which other tests in the session share.
    """
    from app.core.config import Settings

    local_no_smtp = Settings(
        database_url="postgresql+psycopg2://u:p@localhost/db",
        aws_region="us-east-2",
        s3_bucket_name="bucket",
        app_env="local",
        otp_debug=True,
    )
    assert local_no_smtp.expose_otp_in_response

    with_smtp = local_no_smtp.model_copy(update={"smtp_host": "smtp.office365.com"})
    assert not with_smtp.expose_otp_in_response

    in_production = local_no_smtp.model_copy(update={"app_env": "production"})
    assert not in_production.expose_otp_in_response


def test_production_refuses_the_repo_jwt_secret():
    """A shared deployment signing tokens with the secret in the repository
    would let anyone mint an admin token. Caught at construction, not at first
    use, so it stops the process rather than surfacing weeks later."""
    from app.core.config import DEV_JWT_SECRET, Settings

    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(
            database_url="postgresql+psycopg2://u:p@localhost/db",
            aws_region="us-east-2",
            s3_bucket_name="bucket",
            app_env="production",
            jwt_secret=DEV_JWT_SECRET,
        )
