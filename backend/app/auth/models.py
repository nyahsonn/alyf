"""Tables owned by the auth module."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Inspector(Base):
    """A home inspector's account.

    Every document, and through it every home, is scoped to the inspector
    who created it -- see Document.inspector_id (ingestion/models.py) and
    Home.inspector_id (extraction/models.py).
    """

    __tablename__ = "inspectors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    # Nullable: an inspector who only ever signed up via Google/Apple/Facebook
    # has no password of their own -- see OAuthAccount and
    # auth/service.py's find_or_create_from_oauth.
    password_hash: Mapped[str | None] = mapped_column(String(60), nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OAuthAccount(Base):
    """Links one inspector to one identity at one OAuth/OIDC provider.

    An inspector can have several of these (e.g. password + Google, or
    Google + Facebook once linked by matching verified email -- see
    find_or_create_from_oauth). Deleting the inspector deletes these too:
    unlike Document/Home, a linked-account row has no reason to outlive the
    account it identifies.
    """

    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    inspector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inspectors.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # What the provider said at signup, kept for debugging -- not the source
    # of truth for login (provider + provider_user_id is).
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
