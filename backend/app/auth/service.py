"""Password hashing, session tokens, and inspector account lookups."""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Inspector, OAuthAccount
from app.auth.schemas import SignupRequest
from app.core.config import settings

_JWT_ALGORITHM = "HS256"


class OAuthEmailMissingError(Exception):
    """Google returned no email at all (the `email` scope wasn't granted).
    Raised instead of fabricating an identity, so the caller can show a
    clear error instead of creating an unusable account."""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(inspector_id: uuid.UUID) -> str:
    payload = {
        "sub": str(inspector_id),
        "exp": datetime.now(UTC) + timedelta(days=settings.jwt_expires_days),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    """None for anything wrong with the token -- expired, tampered,
    wrong signature, malformed -- rather than raising. Callers (the
    CurrentInspectorDep dependency) turn that into a 401; there is nothing
    about *why* a token failed that should ever reach the client.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


async def get_inspector_by_email(session: AsyncSession, email: str) -> Inspector | None:
    return await session.scalar(select(Inspector).where(Inspector.email == email))


async def get_inspector(session: AsyncSession, inspector_id: uuid.UUID) -> Inspector | None:
    """Used by other modules that need to display an inspector's own name
    (e.g. extraction/service.py's buyer-facing report) -- kept here rather
    than a raw `session.get(Inspector, ...)` in that module, since auth owns
    the `inspectors` table (see README, "modules talk to their neighbours
    only through service calls").
    """
    return await session.get(Inspector, inspector_id)


async def create_inspector(session: AsyncSession, payload: SignupRequest) -> Inspector:
    inspector = Inspector(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        name=payload.name,
    )
    session.add(inspector)
    await session.commit()
    await session.refresh(inspector)
    return inspector


async def authenticate(session: AsyncSession, email: str, password: str) -> Inspector | None:
    inspector = await get_inspector_by_email(session, email.lower())
    if inspector is None or inspector.password_hash is None:
        # None password_hash means an OAuth-only account -- fail cleanly
        # rather than passing None into bcrypt.checkpw.
        return None
    if not verify_password(password, inspector.password_hash):
        return None
    return inspector


async def find_or_create_from_oauth(
    session: AsyncSession,
    *,
    provider: str,
    provider_user_id: str,
    email: str | None,
    email_verified: bool,
    name: str | None,
) -> Inspector:
    """Resolve a Google identity to an Inspector, linking or creating as needed.

    1. An OAuthAccount already links this exact (provider, provider_user_id)
       -> that inspector.
    2. Otherwise, only if Google says the email is verified, an existing
       password-based inspector with that email -> link this identity onto
       that same inspector instead of creating a second account. This is
       the one real security-relevant check in this feature: auto-linking
       on an *unverified* email would let anyone who controls some
       email-adjacent OAuth identity claim an existing account.
    3. Otherwise, create a new inspector with password_hash=None.
    """
    existing_link = await session.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
    )
    if existing_link is not None:
        inspector = await session.get(Inspector, existing_link.inspector_id)
        assert inspector is not None
        return inspector

    if not email:
        raise OAuthEmailMissingError

    inspector = None
    if email_verified:
        inspector = await get_inspector_by_email(session, email.lower())

    if inspector is None:
        inspector = Inspector(email=email.lower(), password_hash=None, name=name)
        session.add(inspector)
        await session.flush()

    session.add(
        OAuthAccount(
            inspector_id=inspector.id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email.lower(),
        )
    )
    await session.commit()
    await session.refresh(inspector)
    return inspector
