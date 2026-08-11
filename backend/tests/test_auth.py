"""Unit tests for password hashing and session tokens. No database or
network needed -- see app/auth/service.py.

Run with:  pytest
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.auth.service import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.core.config import settings


def test_hash_password_round_trips_with_verify():
    password_hash = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", password_hash)


def test_verify_password_rejects_a_wrong_password():
    password_hash = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", password_hash)


def test_hash_password_never_stores_the_plaintext():
    password_hash = hash_password("correct horse battery staple")
    assert "correct horse battery staple" not in password_hash


def test_access_token_round_trips_to_the_same_inspector_id():
    inspector_id = uuid.uuid4()
    token = create_access_token(inspector_id)
    assert decode_access_token(token) == inspector_id


def test_decode_rejects_a_tampered_token():
    token = create_access_token(uuid.uuid4())
    header, payload, signature = token.split(".")
    # The *first* character of a base64url group carries the group's
    # highest-order bits, so changing it always changes the decoded bytes --
    # unlike, say, the last character, which can land on a padding bit that
    # doesn't actually affect the decoded value.
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    tampered = f"{header}.{payload}.{flipped}"
    assert decode_access_token(tampered) is None


def test_decode_rejects_a_token_signed_with_a_different_secret():
    payload = {"sub": str(uuid.uuid4()), "exp": datetime.now(UTC) + timedelta(days=1)}
    token = jwt.encode(payload, "some-other-secret-at-least-32-bytes-long", algorithm="HS256")
    assert decode_access_token(token) is None


def test_decode_rejects_an_expired_token():
    payload = {"sub": str(uuid.uuid4()), "exp": datetime.now(UTC) - timedelta(seconds=1)}
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    assert decode_access_token(token) is None


def test_decode_rejects_garbage():
    assert decode_access_token("not-a-real-token") is None
